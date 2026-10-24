"""Prepare, but do not deploy, a wlroots 0.20.2 cursor-state patch candidate."""
from pathlib import Path
import difflib
import hashlib
import json

root=Path(__file__).resolve().parents[1]
src=root/'out/phoc-commit-20261015/source'
out=root/'out/phoc-commit-20261015/cursor-patch-candidate'
out.mkdir(exist_ok=True)
files={
    'include/backend/drm/drm.h':'wlroots-drm.h',
    'backend/drm/atomic.c':'wlroots-atomic.c',
}
original={name:(src/local).read_text(encoding='utf-8') for name,local in files.items()}
modified=original.copy()
needle='\tuint32_t initial_crtc_id;\n'
assert modified['include/backend/drm/drm.h'].count(needle)==1
modified['include/backend/drm/drm.h']=modified['include/backend/drm/drm.h'].replace(needle,
    '\t/* Atomic only: last successful commit explicitly disabled this plane. */\n'
    '\tbool atomic_known_disabled;\n\n'+needle)
name='backend/drm/atomic.c'
needle='\t\t\t} else {\n\t\t\t\tplane_disable(atom, crtc->cursor);\n\t\t\t}\n'
assert modified[name].count(needle)==1
modified[name]=modified[name].replace(needle,
    '\t\t\t} else if (modeset || !crtc->cursor->atomic_known_disabled) {\n'
    '\t\t\t\t/* Avoid creating a fake commit for an already disabled cursor. */\n'
    '\t\t\t\tplane_disable(atom, crtc->cursor);\n\t\t\t}\n')
needle='\t\tif (ok && !test_only) {\n\t\t\tdrm_atomic_connector_apply_commit(conn_state);'
assert modified[name].count(needle)==1
modified[name]=modified[name].replace(needle,
    '\t\tif (ok && !test_only) {\n'
    '\t\t\tstruct wlr_drm_connector *conn = conn_state->connector;\n'
    '\t\t\tif (conn->crtc->cursor != NULL) {\n'
    '\t\t\t\tconn->crtc->cursor->atomic_known_disabled =\n'
    '\t\t\t\t\t!conn_state->active || !drm_connector_is_cursor_visible(conn);\n'
    '\t\t\t}\n'
    '\t\t\tdrm_atomic_connector_apply_commit(conn_state);')
patch=[]
for name in files:
    target=out/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(modified[name],encoding='utf-8',newline='\n')
    patch.extend(difflib.unified_diff(original[name].splitlines(True),modified[name].splitlines(True),
                                   fromfile='a/'+name,tofile='b/'+name))
(out/'0001-drm-avoid-redundant-disabled-cursor-commits.patch').write_text(''.join(patch),encoding='utf-8',newline='\n')
(out/'status.json').write_text(json.dumps({'upstream':'wlroots 0.20.2','status':'unbuilt, untested candidate; not deployed',
    'source_sha256':{name:hashlib.sha256(original[name].encode()).hexdigest() for name in files}},indent=2)+'\n')
print('Prepared candidate only. Compilation, reset/lease review and atomic-mode device validation remain required.')
