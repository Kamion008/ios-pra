# Giving the agent GitHub CI access

The XNU build needs macOS; the `xnu` workflow runs on `macos-14`. This host is
Linux and `ios-pra` has no remote, so the workflow cannot run until the repo is
on GitHub and `gh` is authenticated.

## A. `gh auth login` (browser, recommended)

`github-cli` is being installed. Then, **in your own terminal** (not through
the agent, so the token never appears in the conversation):

```sh
gh auth login
```

Choose **GitHub.com** → **HTTPS** → **Login with a web browser**, then paste the
one-time code. This stores the token in `~/.config/gh/hosts.yml`; the agent's
shell runs as the same user and will use it.

Verify:

```sh
gh auth status
```

The default `gh` scopes include `repo` and `workflow`, which is what this
build needs. If you want least privilege, use option B.

## B. Fine-grained PAT (least privilege)

1. GitHub → Settings → Developer settings → Personal access tokens →
   **Fine-grained tokens** → Generate new token.
2. Repository access: **Only select repositories** → the repo you will create.
3. Permissions:
   - **Contents**: Read and write
   - **Actions**: Read and write
   - **Workflows**: Read and write
4. In your own terminal:

```sh
printf '%s' 'github_pat_...' | gh auth login --with-token
```

Do not paste the token into the chat.

## After authentication

From `ios-pra`:

```sh
gh repo create ios-pra --private --source=. --remote=origin --push
gh workflow run xnu.yml \
    -f machine_config=PRA \
    -f macos_version=13.5 \
    -f kernel_config=DEVELOPMENT \
    -f keep_going=true
gh run watch
gh run download -n xnu-kernel -D out/ci
tools/pra_package.sh out/ci/kernel.development.pra
```

Or use the helper, which pushes, dispatches, watches, downloads the artifact,
and prints the packaging command:

```sh
tools/pra_ci.sh owner/ios-pra
```

The first run is the risky one: `A5XELTE.h` hardcodes `DREAMLTE`, so PRA is the
first build of the non-DREAMLTE `#else` branches. `0127` and `0128` are already
applied in the workflow's patch directory.
