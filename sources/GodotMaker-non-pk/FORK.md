# GM-Non-PK development fork

Based on [GodotMaker](https://github.com/RandallLiuXin/GodotMaker) commit
`1d4702caa2ac5fdbe1b0139e1787691cb52ae290` (v1.1.0). The original baseline
checkout was preserved unchanged. This local branch has not been published.

The original BUSL 1.1 [LICENSE](LICENSE) applies to this modified distribution.
This is not an Apache-licensed release; its change date is 2030-09-11. Consult
the upstream additional-use grant before commercial redistribution or a
competing hosted service. No planner-kernal code or runtime dependency is added.
Existing user planner state is neither deleted nor adopted.

This fork retains the original gm-* pipeline, PLAN/GAP task authority and
role-owned tests. It adds bounded real checks, isolated immutable-input review
runs, explicit native preview, feedback-to-GAP routing and a shared acceptance
and archive guard. There is no new planner, task database, automatic generator,
React app, HTTP server or SSE service.

`config/review-baseline.json` records the actual engine/runtime tested.
`requirements-review.lock` pins the uv-managed review test environment. The
application never installs dependencies automatically. The current environment
was prepared separately with explicit user permission.

The one-room fixture is handwritten infrastructure test input. Its results do
not establish model generation quality, visuals, audio, physical input devices,
user enjoyment, or a completed human rejection/repair/acceptance loop. N05's
real human acceptance remains required before the proposed N06 workbench.
See [review usage](docs/review.md) and [Chinese usage](docs/zh/review.md).
