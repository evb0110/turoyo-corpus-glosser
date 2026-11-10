# Agent rules

This repository, `evb0110/turoyo-corpus-glosser` (remote `origin`), is the
source of the hosted Turoyo editor at
https://vps-420c0bae.vps.ovh.net/turoyo-editor/ (OVH VPS, container
`turoyo-editor`). Its `main` is what the VPS runs. Make every code change here.

## Other repositories

- `kkashintseva/turoyo-corpus-glosser` (remote `upstream`) is the author's
  repository. `evb0110` has read access only: do not push, open pull requests or
  file issues there. Bring the author's changes in by merging `upstream/main`
  into `main` here.
- `evb0110/turoyo-corpus-glosser-backup` is the VPS's hourly snapshot of source
  and live research data. The next snapshot overwrites any edit made there; use
  it only to recover data.

## Finishing a change

A fix or other requested change is done when it runs on the VPS. Do not stop to
ask for merge or deploy approval.

1. Commit on a branch, push it to `origin`, open a pull request against `main`
   of this repository and merge it yourself. There is no CI or review bot.
2. Deploy as "Turoyo annotation editor" in
   `/home/ubuntu/services-infra/README.md` describes: fast-forward the VPS
   checkout `/home/ubuntu/projects/turoyo-corpus-glosser` to `origin/main`, set
   the `turoyo-editor` image tag in `docker-compose.yml` to the new short SHA,
   build and recreate only that service, then commit and push the services-infra
   files you changed. Commits that change nothing the `Dockerfile` copies (for
   example this file) need no rebuild.
3. Recreating the container drops in-memory edit locks and undo history; saved
   documents persist. Recreate it when `docker logs --since 10m turoyo-editor`
   shows no `POST`, `PATCH` or `DELETE` requests other than `/lock` ones. While
   people are editing, wait for such a gap instead of asking.
4. Verify on the public URL with the credentials in
   `/home/ubuntu/services-infra/.env.turoyo-editor`, using read-only requests.
   Test anything that writes (review ticks, edits) against a copy of
   `/home/ubuntu/services-infra/data/turoyo-editor` in a separate container,
   never on live documents.

## Tests

The image has no pytest. Run the suite in it from a checkout:

```sh
docker run --rm -v "$PWD:/work" -w /work -e HOME=/tmp --user 1000:1000 \
  --entrypoint sh turoyo-corpus-glosser:<tag> -c \
  'python -m pip install -q --user pytest httpx && PYTHONPATH=/work/src python -m pytest -p no:cacheprovider -rf'
```

It takes about 15 minutes. Nine tests already fail on upstream `405f2d8`, in
`test_editor_flextext_import.py`, `test_lift_fieldworks.py`,
`test_turoyo_verb_parser_editor.py` and `tests/unit/test_turoyo_verbs.py`.
Compare failures with `main` before attributing one to your change.
