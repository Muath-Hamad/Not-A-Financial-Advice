# 08 — Version history

Three seasons. Each changed the question being asked, so the results are not
directly comparable across versions — the universe, cost model and agent
objectives all differ.

| | v1 | v2 | v3 |
|---|---|---|---|
| Universe | Top 50 by size | Full main market (160) | Full main market (160) |
| Agents | 8 personalities | 9 (+ meta-agent) | 8 profit-maximizers |
| Objective | Play the character | Play the character | **Maximize profit** |
| Commission | 15.5 bps + 15% VAT ≈ 17.8 bps | 8 bps | 8 bps |
| Slippage | 10 bps | 5 bps | 5 bps |
| Inter-agent chat | Yes ("majlis") | Yes | **No** — journals only |
| Peer books | No | Yes | Yes |
| Winner | 🧕 Um Khalid +21.6% | 🐆 Lulu +82.0% | 🦅 Saqr +367.9% |
| Artifact | [v1](https://claude.ai/code/artifact/391549c3-5ac9-4159-bd52-80b9fe30fac8) | [v2](https://claude.ai/code/artifact/c250b1fc-1e1c-41d7-b53b-5336538e1030) | [v3](https://claude.ai/code/artifact/6879479b-0a0d-4b2f-8c41-8c0639891d86) |
| Archive | `archive/v1/` | `archive/v2/` | current `sim/`, `out/`, `dashboard/` |

## v1 — the majlis (top 50)

Eight agents with strong personalities — a dividend matriarch, a souq veteran, a
quant, a degen day-trader, a contrarian, a macro strategist, a panicky
accountant, an influencer — each authoring its own strategy from its character.

**Innovation:** the *majlis*, a shared board where every agent posted sentiment,
mood and messages after each close, readable by all the next day. This was
genuine inter-agent communication with feedback into decisions: the contrarian
computed the crowd's average sentiment and faded extremes; the influencer
followed it with a lag.

**Result:** Um Khalid +21.6% vs TASI −5.0%. Seven of eight beat the index. The
telling detail: she collected SAR 19,662 in dividends and paid SAR 259 in
commissions, while the day-trader paid SAR 25,269 in commissions — most of his
−29% was self-inflicted friction.

**Lesson carried forward:** costs dominate high-turnover strategies, and patience
compounds when the index does not.

## v2 — the whole market

**Changes:** full main-market universe (multi-source discovery), commissions cut
to 8 bps, slippage to 5 bps, and a ninth agent — **Zahab**, a meta-agent that
allocated purely on peers' proven track records. This required a new engine
channel, `ctx["peers"]`, exposing every agent's public book daily.

**Zahab's two good ideas**, both inherited by v3's Malik:
* a **churn charge** when grading peers — a one-day-lagged copy of a fast trader
  only ever buys his exits, so high-turnover peers were penalized
* a **tuition ledger** — accumulate the whole field's realized P&L per ticker and
  penalize names where the group has collectively lost money

**Result:** Lulu (crowd-following momentum) +82.0%; Zahab +39.1% at a −17.3%
drawdown — second place on return, and the best drawdown of any agent that
actually deployed capital (only the half-in-cash accountant sat shallower, at
−10.9% for +3.1%). The wider universe reshuffled everything — momentum improved
with 160 names to scan, knife-catching got more dangerous (the contrarian fell
to −20.5%).

**Lesson carried forward:** copying graded peers works, but pure imitation can
never beat its best source.

## v3 — the arena

**Changes:**
* **Chat removed.** No `shout`, no `majlis`; agents keep private journals only.
  Competition runs through performance and peer books alone.
* **Objective unified.** Every agent purely maximizes terminal equity. Character
  survives only as journal voice.
* **Strategy freedom.** Each agent was assigned a *school* as a starting
  philosophy but told explicitly it could mix and adapt techniques.
* **Mandatory study.** Every author had to read `archive/v2/` — results, briefs
  and the actual strategy code — before designing. The lineage shows: Badr's
  design is an autopsy of v2's contrarian, Raad's of v2's degen.
* **Fairness audit added.** All eight files checked for hardcoded dates and
  per-ticker trade plans; zero found.
* **Engine hardening.** Forced exit after 20 silent sessions, so delisted names
  cannot mark at a stale price forever.

**Result:** Saqr +367.9%, all eight agents beating the index by >125 points —
a result suspicious enough to demand the out-of-sample test, which duly showed
Saqr collapsing to 7th and **Raad** emerging as the genuinely best agent.

**Lesson:** in-sample dominance ranks *fitting quality*, not *investment quality*.

## What each season contributed to the final answer

| Season | Contribution |
|---|---|
| v1 | Cost sensitivity; dividends as a real return component; the value of low turnover |
| v2 | Universe breadth changes which strategies work; peer information is exploitable; imitation has a ceiling |
| v3 | Explicit profit objective + inherited lessons produce far better strategies — and a validation methodology capable of exposing their limits |

## Archive contents

```
archive/v1/  README.md, dashboard.html, results.json, commentary.json
archive/v2/  README.md, dashboard.html, results.json, commentary.json,
             briefs.json, strategies/*.py   (the majlis-era agent code)
```

Each README records the exact commit SHA of that season's final state and its
frozen artifact URL. The v1 archive has no `strategies/` directory — those files
were superseded in place before archiving became the practice; they are
recoverable from the v1 commit if ever needed.
