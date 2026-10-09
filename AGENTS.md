# Local execution policy

Strictly forbidden hash check at building.

The user explicitly authorized Git to replace SHA checks. Use Git commits,
scoped inventories, native object identities and diffs for the active local
build/review workflow. Do not invoke standalone SHA/MD5 checks or the legacy
package checksum helpers as a build prerequisite.

Read `LOCAL-SETUP-GIT.zh-CN.md` for the installed Godot path and migrated
metadata. Fields historically named `*_digest` / `report_digests` now carry
Git identities; active run metadata uses `manifest.git` and
`evaluation-binding.git`. Historical SHA manifests, source ZIPs and old
documentation examples remain provenance, not current build instructions.

The reviewed frontend source still differs from the delivered game in
`scripts/ui/hud.gd` and `scripts/ui/title_screen.gd`. Preserve these rejection
checks until their source/adapter differences are explicitly reviewed. Git
migration does not grant new gameplay scope or replace required human decisions.
