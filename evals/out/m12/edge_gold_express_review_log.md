# Review log: heldout-express (v5.2.1, dbac741)

Reviewer labelled all 30 sites independently from source (scratch file scratch_review_edge_express.json) before opening the author's file.

Result: 30/30 agreements, 0 changes. Site fields (path, line, col, callee_text, snippet, node_type) match the input jsonl for all 30 sites; repo_id, tag and commit_sha verified.

Doubtful sites checked by reading code:
- 12 (mvc main/index.js res.redirect): handler exported and registered on an express app by examples/mvc/lib/boot.js via app[method]; convention applied, label is lib/response.js res.redirect. Agreed.
- 20 (route-separation site.js res.render): site.index registered with app.get in the example index.js; convention applied, lib/response.js res.render. Agreed.
- 28 (lib/request.js trust(...)): value read from the settings table (app.get('trust proxy fn')); may be a user function, a compileTrust closure or proxyaddr.compile result, so dynamic. Agreed.

No changes made to out/edge_gold_heldout_express.json. `reviewed` left false (orchestrator sets it).

VERDICT: approved
