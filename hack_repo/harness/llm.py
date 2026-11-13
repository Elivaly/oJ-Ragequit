"""LLM gateway: openJiuwen primary, OpenAI fallback. Adaptive concurrency."""
import asyncio, calendar, os, re, time
from dataclasses import dataclass
from .core import CFG, TMP, RateLimiter, est_tokens

@dataclass
class CallResult:
    ok: bool = False
    text: str = ""
    reasoning: str = ""
    in_tok: int = 0
    out_tok: int = 0
    cost: float = 0.0
    error: str = ""
    model: str = ""
    latency: float = 0.0

def _content_to_str(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content)
    return str(content or "")

def _classify(e):
    s = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code in (401, 403) or "api key" in s or "unauthorized" in s or "blocked" in s:
        return "auth"
    if code == 402 or "wallet" in s or "quota" in s or "exhausted" in s or "insufficient" in s:
        return "quota"
    if code == 429 or "too many" in s or "одновременн" in s or "rate limit" in s or "rate_limit" in s:
        return "rate"
    if code == 400 and ("context" in s or "too long" in s or "maximum" in s):
        return "context"
    if ("connection error" in s or "getaddrinfo" in s or "name or service not known" in s
            or "invalid url" in s or "unsupported protocol" in s or "connecterror" in s):
        return "connect"
    if (code and 500 <= code < 600) or "timeout" in s or "timed out" in s or "overloaded" in s or "unavailable" in s or "connection" in s:
        return "transient"
    return "fatal"

def _is_concurrency(e):
    s = str(e).lower()
    return ("одновременн" in s or "inflight" in s or "in-flight" in s
            or "parallel" in s or "concurrent" in s)

def _retry_after(e, default):
    resp = getattr(e, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", None) or {}
        try:
            v = headers.get("retry-after") or headers.get("Retry-After")
            if v:
                return float(v)
        except Exception:
            pass
    s = str(e)
    m = re.search(r"через\s+(\d+)\s*с", s) or re.search(r"Retry in (\d+)", s)
    if m:
        return float(m.group(1))
    m = re.search(r"Limit resets at:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC", s)
    if m:
        try:
            ts = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            return max(0.5, ts - time.time() + 0.4)
        except Exception:
            pass
    return default

class Gate:
    """Limits how many requests are in flight at once; shrinks on 429."""
    def __init__(self, limit):
        self.limit = max(1, limit)
        self.active = 0
        self.cond = asyncio.Condition()
    async def __aenter__(self):
        async with self.cond:
            while self.active >= self.limit:
                await self.cond.wait()
            self.active += 1
        return self
    async def __aexit__(self, *exc):
        async with self.cond:
            self.active -= 1
            self.cond.notify_all()
    def shrink(self):
        if self.limit > 1:
            self.limit -= 1
            print(f"[gateway] concurrency ceiling lowered to {self.limit}")

class _Ojw:
    def __init__(self, base_url, api_key):
        import copy
        from openjiuwen.core.common.logging.log_config import configure_log_config
        from openjiuwen.core.common.logging.default.constant import DEFAULT_LOG_CONFIG
        log_dir = os.path.join(TMP, "ojw_logs") + os.sep
        inner = copy.deepcopy(DEFAULT_LOG_CONFIG)["logging"]
        inner.update({"log_path": log_dir, "level": "CRITICAL", "output": ["console"],
                      "interface_output": ["console"], "performance_output": ["console"]})
        try:
            configure_log_config(inner)
        except Exception as e:
            print(f"[gateway] log config retry: {e}")
            try:
                configure_log_config({"backend": "default", "level": "CRITICAL",
                                      "output": ["console"], "log_path": log_dir})
            except Exception as e2:
                print(f"[gateway] log config skipped: {e2}")
        from openjiuwen.core.foundation.llm import Model, ModelClientConfig, ModelRequestConfig
        self._model = Model(
            model_client_config=ModelClientConfig(
                client_provider="OpenAI", api_key=api_key, api_base=base_url,
                timeout=300.0,
                verify_ssl=os.environ.get("LLM_SSL_VERIFY", "true").lower() != "false"),
            model_config=ModelRequestConfig(model=CFG.fast))

    async def __call__(self, messages, model, max_tokens, temperature, timeout):
        m = await self._model.invoke(messages=messages, model=model,
                                     max_tokens=max_tokens, temperature=temperature,
                                     timeout=timeout)
        u = m.usage_metadata
        return (_content_to_str(m.content), m.reasoning_content or "",
                int(getattr(u, "input_tokens", 0) or 0),
                int(getattr(u, "output_tokens", 0) or 0),
                int(getattr(u, "reasoning_tokens", 0) or 0))

class _OpenAI:
    def __init__(self, base_url, api_key):
        from openai import AsyncOpenAI
        self._c = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=300.0, max_retries=0)

    async def __call__(self, messages, model, max_tokens, temperature, timeout):
        r = await self._c.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout)
        msg = r.choices[0].message
        u = r.usage
        rt = 0
        det = getattr(u, "completion_tokens_details", None)
        if det is not None:
            rt = int(getattr(det, "reasoning_tokens", 0) or 0)
        return (_content_to_str(msg.content), getattr(msg, "reasoning_content", "") or "",
                int(u.prompt_tokens or 0), int(u.completion_tokens or 0), rt)

class Gateway:
    def __init__(self, ledger, trace, base_url=None, api_key=None):
        self.ledger = ledger
        self.trace = trace
        self.rl = RateLimiter(CFG.rpm)
        self.gate = Gate(int(os.environ.get("HARNESS_INFLIGHT", "3")))
        base_url = base_url or os.environ.get("LLM_BASE_URL", "")
        api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.transports = []
        for cls in (_Ojw, _OpenAI):
            try:
                self.transports.append(cls(base_url, api_key))
            except Exception as e:
                print(f"[gateway] transport {cls.__name__} unavailable: {e}")
        if not self.transports:
            raise RuntimeError("no usable LLM transport")
        print(f"[gateway] primary transport: {type(self.transports[0]).__name__}, "
              f"in-flight limit {self.gate.limit}")
        self.consecutive_failures = 0
        self.rate_streak = 0
        self.total_ok = 0
        
    async def call(self, messages, *, model, max_tokens, temperature=0.0,
                   timeout=120, purpose="", task_id=None):
        led = self.ledger
        if led.exhausted:
            return CallResult(error="budget", model=model)
        est_in = sum(est_tokens(_content_to_str(m["content"])) for m in messages)
        reserve = est_in / 10.0 + max_tokens
        if not led.try_reserve(reserve):
            return CallResult(error="budget", model=model)
        t0 = time.monotonic()
        last_err = "fatal"
        for attempt in range(6):
            tr = self.transports[0] if attempt < 4 else self.transports[-1]
            try:
                async with self.gate:
                    await self.rl.acquire()
                    payload = await tr(messages, model, max_tokens, temperature, timeout)
                text, reasoning, it, ot, rt = payload
                it = it or est_in
                out = max(ot, rt)
                if reasoning and rt == 0 and ot == 0:
                    out = est_tokens(reasoning)
                cost = out + it / 10.0
                led.commit(reserve, cost)
                self.total_ok += 1
                self.consecutive_failures = 0
                self.rate_streak = 0
                res = CallResult(ok=True, text=text, reasoning=reasoning, in_tok=it,
                                 out_tok=out, cost=cost, model=model,
                                 latency=time.monotonic() - t0)
                self._trace(task_id, purpose, res, "")
                return res
            except Exception as e:
                last_err = _classify(e)
                if last_err == "rate":
                    self.rate_streak += 1
                    if _is_concurrency(e):
                        self.gate.shrink()
                    if self.rate_streak >= 40:
                        led.mark_exhausted()
                        break
                    await asyncio.sleep(min(_retry_after(e, 2.0 + attempt), 65.0))
                    continue
                if last_err in ("transient", "connect") and attempt < 3:
                    await asyncio.sleep(2.0 + 2.0 * attempt)
                    continue
                break
        if last_err in ("auth", "quota", "rate", "context", "connect"):
            penalty = 0.0
        elif last_err == "transient":
            penalty = est_in / 10.0 + min(max_tokens, 128)
        else:
            penalty = est_in / 10.0
        led.commit(reserve, penalty)
        if last_err != "rate":
            self.consecutive_failures += 1
        if (last_err in ("auth", "quota", "connect") and self.total_ok == 0
                and self.consecutive_failures >= 4):
            print("[gateway] proxy/key unusable, stopping")
            led.mark_exhausted()
        elif last_err in ("auth", "quota") and led.spent > 0.5 * led.budget:
            led.mark_exhausted()
        elif self.consecutive_failures >= 15:
            led.mark_exhausted()
        res = CallResult(error=last_err, model=model, cost=penalty,
                         latency=time.monotonic() - t0)
        self._trace(task_id, purpose, res, last_err)
        return res

    def _trace(self, task_id, purpose, res, err):
        self.trace.write({"type": "call", "task": task_id, "purpose": purpose,
                          "model": res.model, "in": res.in_tok, "out": res.out_tok,
                          "cost": round(res.cost, 1), "latency": round(res.latency, 2),
                          "error": err, "ts": time.time()})