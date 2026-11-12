# ADR-0011: Product checks in the deterministic test stage

- Status: Accepted by the maintainer on 2026-11-12; delivered locally outside the factory pipeline (as ADR-0010, decision 14)
- Date: 2026-11-12
- Deciders: Felix (`ftrutschnig`)
- Related: [ADR-0010](0010-product-stack.md), [architecture](../architecture/AICEPEAK_ARCHITECTURE.md#product-checks), [policy](../../factory/policy.md), [test image](../../factory/clients.md#test-image)

## Context

ADR-0010 chose the stack and left `product_checks_ready` at `false` until the .NET and TypeScript builds and tests run as checks. The deterministic test stage (`tools/factory/engine.py test`, job "Deterministic tests") only ran `verify.py --ci`: repository-wide syntax, link, workflow and secret checks and the factory's own unit tests. The policy allows PR code only in an environment without secrets, host home, Docker socket and network, and no PR-controlled install or hook script in a privileged job.

## Decision

1. **Steps.** The test stage runs these steps, each its own sandboxed `docker run` in the trusted test image ([factory/test.Dockerfile](../../factory/test.Dockerfile)) with the same isolation (no network, read-only root, no capabilities, no new privileges, process, memory and CPU limits, no Docker socket, no credentials). A failing step does not stop the others:

   | Step | Command (trusted constant) |
   |---|---|
   | `factory` | `verify.py --ci` (unchanged) |
   | `backend-deps` | trusted NuGet fetch (below) |
   | `backend-build` | `dotnet build Aicepeak.slnx -warnaserror` with an offline, locked restore |
   | `backend-test` | `dotnet test --no-build --filter "Category!=Database"` with a TRX logger; skipped after a failed build |
   | `frontend-deps` | trusted npm fetch (below) |
   | `frontend-lint` | `node_modules/.bin/oxlint --deny-warnings` |
   | `frontend-test` | `node_modules/.bin/vitest run` with a JUnit reporter |
   | `frontend-build` | `node_modules/.bin/tsc -b && node_modules/.bin/vite build` |

   The commands are constants in [tools/factory/steps.py](../../tools/factory/steps.py) on the config branch; a PR's `package.json` scripts never decide what runs. An area without its markers (`backend/Aicepeak.slnx`; `frontend/package.json` and `package-lock.json`) is reported as not present. Steps that write get a throwaway copy of the candidate. All steps share one time budget (`limits.timeout_seconds`); a timeout removes the container.

2. **Dependencies without PR code.**
   - **npm:** the host checks `package.json` and `package-lock.json`: only `registry.npmjs.org` tarballs with sha512 integrity, no links, no git/file/http specifiers, no workspaces. Then `npm ci --ignore-scripts` runs in a fetch container from the test image that has network but sees only copies of those two files: no project or user `.npmrc`, no scripts, no credentials. npm verifies every tarball.
   - **NuGet:** `backend/**/packages.lock.json` (committed, `RestorePackagesWithLockFile`) pins every package. The host downloads each by exact id and version from the nuget.org flat container into a folder feed. The sandbox restores offline in locked mode with a trusted `nuget.config` that lists only that feed. NuGet itself rejects a package whose content differs from the lock (`NU1403`) or whose signature is broken (`NU3005`); both were verified with tampered packages.
3. **Results.** The exit code decides each step; a failed test case can only turn a step red. Trusted host code reads TRX and JUnit files (regular files only, size-bounded, no DTDs) and compiler/lint output. The run's **job summary** lists every test case, failure details, errors and the output of failing steps. `factory/deterministic`, still the only gate, shows a short step table with a link to it, and up to 50 **annotations** at failing tests and compiler/lint errors in the PR diff. Untrusted text is escaped so it cannot break tables, add links or mention anyone; PR output never reaches the job log.
4. **Database tests.** Tests with `Category=Database` need Testcontainers and therefore the Docker socket, which the policy forbids in the sandbox. They are not run in the pipeline and the summary says so. A pinned PostgreSQL on an internal network without internet access is the intended follow-up; it needs an explicit policy decision.
5. **Readiness.** With these checks the maintainers set `product_checks_ready: true`; `product` work orders are no longer blocked.

## Consequences

- **What the PR still controls:** the tests, the lint configuration and the locked package versions remain under the PR's control; review covers them. A PR could remove or add the `Category=Database` trait; the test counts in the job summary make that visible.
- **Lock files:** after a package change, `dotnet restore backend/Aicepeak.slnx --force-evaluate` and the updated `packages.lock.json` belong in the same change. Otherwise `backend-deps` or `backend-build` fails (`NU1004`, `NU1101`).
- **Vulnerability audit offline:** NuGet's vulnerability audit cannot run offline (`NuGetAudit=false` in the sandbox). Dependabot covers advisories for now.
- **Runtime and resources:** measured locally, all steps take about 2 minutes on top of today's factory checks. The tests job's `timeout-minutes` rises from 25 to 35.
- **Takes effect on promotion:** the steps take effect once this code reaches the config branch `production`.
