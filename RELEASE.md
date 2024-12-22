# Release Process

## Preparation

### Version Bump and Changelog

1. Bump the version in [`dev_cmd/__init__.py`](dev_cmd/__init__.py).
2. Run `uv run dev-cmd` as a sanity check on the state of the project.
3. Update [`CHANGES.md`](CHANGES.md) with any changes that are likely to be useful to consumers.
4. Open a PR with these changes and land it on https://github.com/jsirois/dev-cmd main.

## Release

### Push Release Tag

Sync a local branch with https://github.com/jsirois/dev-cmd main and confirm it has the version bump
and changelog update as the tip commit:

```
$ git log --stat -1 HEAD | grep -E "CHANGES|__init__"
 CHANGES.md                    |   5 +
 dev_cmd/__init__.py           |   4 +```

Tag the release as `v<version>` and push the tag to https://github.com/jsirois/dev-cmd main:

```
$ git tag --sign -am 'Release 0.1.0' v0.1.0
$ git push --tags https://github.com/jsirois/dev-cmd HEAD:main
```

The release is automated and will create a PyPI release at
[https://pypi.org/project/dev-cmd/&lt;version&gt;/](https://pypi.org/project/dev-cmd/#history).
