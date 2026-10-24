# Cost, quality, and latency

`account_cost` adds integer prices. A boolean or any non-integer, including a missing price, returns `total: "UNKNOWN"`. It does not return 0 for an unknown price. Currency defaults to the string `UNKNOWN` when the caller omits it. No provider price was fetched.

On the unsupported equation, quality changes between 1 and 2 handlers and does not change again at 3, 5, or 10. Size 16 was not run. Call count is the team size. Wall-clock latency was not measured; the functions return inside one pytest process. p50 and p95 are not reported.

`bound_deadline` returns `INCOMPLETE` with `fabricated_completion: false` when the used ticks meet the budget and the work is not done.
