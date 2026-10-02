"""Provider adapters for olb.memory.extract/1 (Lane A2). Provider-independent: every adapter returns
(text, meta) where meta always carries provider, model_requested, model_reported, stop_reason, tokens,
cost_usd, latency_s and provider_version.

- ClaudeCLIProvider: the local `claude` CLI in headless mode (no tools, no session, replaced system prompt).
- AnthropicAPIProvider: the Anthropic Messages API (needs ANTHROPIC_API_KEY; not available in this workspace).
- CachedProvider: wraps any provider; responses are stored by request hash, so a run can be replayed and
  re-scored offline under any core configuration without new model calls.

Synthetic benchmark data only. Never production conversations.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import time


class ClaudeCLIProvider:
    name = "claude-cli"

    def __init__(self, model: str, timeout: int = 240):
        self.model = model
        self.timeout = timeout
        try:
            self.version = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                                          timeout=60).stdout.strip()
        except Exception:
            self.version = "unknown"

    def complete(self, system: str, user: str):
        t0 = time.time()
        with tempfile.TemporaryDirectory() as tmp:                     # no project context, no CLAUDE.md
            p = subprocess.run(["claude", "-p", "--system-prompt", system, "--tools", "", "--model", self.model,
                                "--no-session-persistence", "--strict-mcp-config", "--output-format", "json"],
                               input=user, capture_output=True, text=True, encoding="utf-8", timeout=self.timeout,
                               cwd=tmp)
        dt = time.time() - t0
        try:
            d = json.loads(p.stdout)
        except Exception:
            return None, {"provider": self.name, "model_requested": self.model, "error": (p.stderr or p.stdout)[:500],
                          "latency_s": dt, "provider_version": self.version}
        if d.get("is_error") or str(d.get("result", "")).startswith("You've hit your"):
            # account/session limits and CLI errors are provider errors, never model output (never cached)
            return None, {"provider": self.name, "model_requested": self.model, "provider_version": self.version,
                          "error": "provider_error: " + str(d.get("result", ""))[:160], "latency_s": dt}
        usage = d.get("modelUsage", {})
        reported = [k for k in usage if "haiku" not in k or "haiku" in self.model] or list(usage)
        main = reported[0] if reported else None
        mu = usage.get(main, {}) if main else {}
        return d.get("result"), {
            "provider": self.name, "provider_version": self.version, "model_requested": self.model,
            "model_reported": mu.get("canonicalModel") or main, "stop_reason": d.get("stop_reason"),
            "input_tokens": mu.get("inputTokens"), "output_tokens": mu.get("outputTokens"),
            "cost_usd": d.get("total_cost_usd"), "latency_s": round(dt, 2), "is_error": d.get("is_error", False)}


class AnthropicAPIProvider:
    name = "anthropic-api"

    def __init__(self, model: str, max_tokens: int = 2048):
        import anthropic                                                 # noqa: F401 (optional dependency)
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.version = "anthropic-sdk-" + anthropic.__version__

    def complete(self, system: str, user: str):
        t0 = time.time()
        r = self.client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system,
                                        messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, {"provider": self.name, "provider_version": self.version, "model_requested": self.model,
                      "model_reported": r.model, "stop_reason": r.stop_reason,
                      "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
                      "cost_usd": None, "latency_s": round(time.time() - t0, 2)}


class CachedProvider:
    def __init__(self, inner, cache_dir: str, rep: int = 0, offline: bool = False):
        self.inner, self.cache_dir, self.rep, self.offline = inner, cache_dir, rep, offline
        os.makedirs(cache_dir, exist_ok=True)

    def key(self, system: str, user: str) -> str:
        h = hashlib.sha256(json.dumps([self.inner.name, self.inner.model, self.rep, system, user]).encode()).hexdigest()
        return h[:32]

    def complete(self, system: str, user: str):
        k = self.key(system, user)
        path = os.path.join(self.cache_dir, k + ".json")
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            d["meta"]["cache"] = "hit"
            return d["text"], d["meta"]
        if self.offline:
            return None, {"provider": self.inner.name, "model_requested": self.inner.model, "error": "offline_miss"}
        text, meta = self.inner.complete(system, user)
        meta["request_hash"] = k
        meta["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if text is not None:
            json.dump({"text": text, "meta": meta}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        meta = dict(meta, cache="miss")
        return text, meta
