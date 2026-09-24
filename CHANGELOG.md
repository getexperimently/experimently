# Changelog

## [0.2.1](https://github.com/amarkanday/experimentation-platform/compare/v0.2.0...v0.2.1) (2026-09-24)


### Bug Fixes

* **publish:** build the docs site from the export, where it actually fails ([#315](https://github.com/amarkanday/experimentation-platform/issues/315)) ([970e6fe](https://github.com/amarkanday/experimentation-platform/commit/970e6fed2391db8e3a0bae07435bcc73e2726a7e))
* **publish:** stop shipping the Dependabot config to the public repository ([#316](https://github.com/amarkanday/experimentation-platform/issues/316)) ([6fc6757](https://github.com/amarkanday/experimentation-platform/commit/6fc6757f496b6b9688e102b625edbc7bd89aa3c5))
* the release bumped VERSION and left three fixtures on 0.1.0 ([#313](https://github.com/amarkanday/experimentation-platform/issues/313)) ([7eb6a4d](https://github.com/amarkanday/experimentation-platform/commit/7eb6a4d142ff9e61e64ca0e6ad36560ef2536479))


### Documentation

* the release and cut procedure, and push tags explicitly ([#317](https://github.com/amarkanday/experimentation-platform/issues/317)) ([7a82c68](https://github.com/amarkanday/experimentation-platform/commit/7a82c681b553510a715691a3e7f015851c6ddcbc))

## [0.2.0](https://github.com/amarkanday/experimentation-platform/compare/v0.1.0...v0.2.0) (2026-09-24)


### Features

* **cut:** the DCO check CONTRIBUTING.md already promised, and item 12 measured ([54e5865](https://github.com/amarkanday/experimentation-platform/commit/54e586500f6f9844497131ea0357b94c8aa4b1eb))
* **dashboard:** a public homepage at /, with the dashboard still behind auth ([#281](https://github.com/amarkanday/experimentation-platform/issues/281)) ([8ca8242](https://github.com/amarkanday/experimentation-platform/commit/8ca824298d4e6efb6a6cf18201d61d1169677234))


### Bug Fixes

* a rate-limited login reads as a rate-limited login, not as a dead API ([#210](https://github.com/amarkanday/experimentation-platform/issues/210)) ([466505f](https://github.com/amarkanday/experimentation-platform/commit/466505f6f19d725f46dbbe3f6ce9f3522a70e6c1))
* **assignment:** one consistent hash, the one every SDK implements ([#282](https://github.com/amarkanday/experimentation-platform/issues/282)) ([9ec069a](https://github.com/amarkanday/experimentation-platform/commit/9ec069a37f069010f7f7e48ea9963913fa10a6a6))
* break the CDK dependency cycle, and run a real cdk synth on every PR ([#174](https://github.com/amarkanday/experimentation-platform/issues/174)) ([fe6807a](https://github.com/amarkanday/experimentation-platform/commit/fe6807ac56dffed94a10cdc815115ccbdc3ca3c1))
* **ci:** lock refresh survives an unresolvable PR, and approves the runs its push creates ([#190](https://github.com/amarkanday/experimentation-platform/issues/190)) ([f9d47ae](https://github.com/amarkanday/experimentation-platform/commit/f9d47ae5da334e852fb0f0fab0f200c70cf43b67))
* **ci:** Performance Tests never passed — the repo root was off by one ([204f86b](https://github.com/amarkanday/experimentation-platform/commit/204f86b8766239d526899252863fec8ce409d8ca))
* **ci:** poll for the runs to approve instead of sleeping once ([#196](https://github.com/amarkanday/experimentation-platform/issues/196)) ([03d0b87](https://github.com/amarkanday/experimentation-platform/commit/03d0b8749b29c532d256916dfe285d797da64763))
* **ci:** the lock refresh ran its checker from /tmp, and one bad PR aborted the run ([#189](https://github.com/amarkanday/experimentation-platform/issues/189)) ([0590e94](https://github.com/amarkanday/experimentation-platform/commit/0590e945839bb6c3f8a06ef2702c98ffa3c2d958))
* close two security groups that were open to the whole internet ([#193](https://github.com/amarkanday/experimentation-platform/issues/193)) ([f946463](https://github.com/amarkanday/experimentation-platform/commit/f9464633af8f90c8d12a603c69b3dae18adf7c4c))
* counter writes land on the experiment the URL names ([#216](https://github.com/amarkanday/experimentation-platform/issues/216)) ([fbebeb4](https://github.com/amarkanday/experimentation-platform/commit/fbebeb449069fb02cd26a5c83a977d1713f78e87))
* **cut:** the export gate could only find what someone remembered to list ([99c04f7](https://github.com/amarkanday/experimentation-platform/commit/99c04f72b6c0c8bf29e17e1ada068a4a6ac9047b))
* **dashboard:** every docs link pointed at a site that has never been built ([#289](https://github.com/amarkanday/experimentation-platform/issues/289)) ([8a0005a](https://github.com/amarkanday/experimentation-platform/commit/8a0005a134fb331421aa7fe8b39f111c3aee262f))
* **demo:** move both demo apps to Next 16 and React 19, clearing the critical advisory ([#192](https://github.com/amarkanday/experimentation-platform/issues/192)) ([4fbdaf8](https://github.com/amarkanday/experimentation-platform/commit/4fbdaf85120697037a69a5bcfbdbe489131042b8))
* deploy-prod stops building a dashboard image nothing could receive ([#207](https://github.com/amarkanday/experimentation-platform/issues/207)) ([410bb0f](https://github.com/amarkanday/experimentation-platform/commit/410bb0fde953975c9ced59d078e9cf5774041b96))
* **deploy:** name the ECR repository the same in every tree ([#221](https://github.com/amarkanday/experimentation-platform/issues/221)) ([afe9acb](https://github.com/amarkanday/experimentation-platform/commit/afe9acbaacd8e7f5acc01a4753f7d0f75ae5a595))
* **deploy:** roll back through CodeDeploy, and approve the traffic shift ([b9efd11](https://github.com/amarkanday/experimentation-platform/commit/b9efd117409c4ed22d84e16689c6378b4d4ee620))
* **deps:** gunicorn 21.2.0 -&gt; 22.0.0, two request-smuggling advisories ([#293](https://github.com/amarkanday/experimentation-platform/issues/293)) ([171ce6f](https://github.com/amarkanday/experimentation-platform/commit/171ce6fae6743a22968676f43b79f2dac3eb8911))
* deterministic CDK resource names, and one Glue catalog instead of two ([#177](https://github.com/amarkanday/experimentation-platform/issues/177)) ([2b93a72](https://github.com/amarkanday/experimentation-platform/commit/2b93a72805841b9c61ea3ad2dde7da7744fc38c3))
* enforce the LIST permission on the experiments list endpoint ([#204](https://github.com/amarkanday/experimentation-platform/issues/204)) ([3ee9126](https://github.com/amarkanday/experimentation-platform/commit/3ee9126e79673d5cf19f053d944ea740d964894c))
* **licences:** regenerate the attribution record in an environment that matches the distribution ([#215](https://github.com/amarkanday/experimentation-platform/issues/215)) ([a7309c8](https://github.com/amarkanday/experimentation-platform/commit/a7309c861a7c42805f60a3305bd87aeb95fffe8e))
* name the ECS cluster, and correct three drifted names in the rollback runbook ([#194](https://github.com/amarkanday/experimentation-platform/issues/194)) ([530e278](https://github.com/amarkanday/experimentation-platform/commit/530e27846dfa24e2a1958684f9cf67681f4bb65b))
* **publish:** sweep commit messages, and stop the gate shipping the strings it forbids ([#288](https://github.com/amarkanday/experimentation-platform/issues/288)) ([89f72a1](https://github.com/amarkanday/experimentation-platform/commit/89f72a123f40640a3dfd45b05e42dca137971aa2))
* **publish:** the settings script reported ok for a setting it never applied ([#295](https://github.com/amarkanday/experimentation-platform/issues/295)) ([4e945b2](https://github.com/amarkanday/experimentation-platform/commit/4e945b223ee271c6bd1bf8841f24754234204e0c))
* **sdk:** clear the critical and every high-severity lockfile advisory ([#290](https://github.com/amarkanday/experimentation-platform/issues/290)) ([851f0c2](https://github.com/amarkanday/experimentation-platform/commit/851f0c264c77a9463ba8ba52d8c08400131be943))
* **security:** honour --tier, refuse duplicate exceptions, drop a gate that scanned one file ([#219](https://github.com/amarkanday/experimentation-platform/issues/219)) ([d72d3e6](https://github.com/amarkanday/experimentation-platform/commit/d72d3e689ff90017ff6da179e08180a91ae24a6f))
* stop publishing an arm64 image that cannot run, and delete a drifted requirements file ([#191](https://github.com/amarkanday/experimentation-platform/issues/191)) ([380e651](https://github.com/amarkanday/experimentation-platform/commit/380e651ce0c2145e1674860f2125d5bdff8c0b0d))
* the admin area asks the question the admin API asks ([#206](https://github.com/amarkanday/experimentation-platform/issues/206)) ([1774652](https://github.com/amarkanday/experimentation-platform/commit/1774652bc1183fc19c11e486d9e0eee97c6e1a34))
* the ECR gate did not gate, and its docstring described a reverted design ([#224](https://github.com/amarkanday/experimentation-platform/issues/224)) ([0eb1c43](https://github.com/amarkanday/experimentation-platform/commit/0eb1c43900ef07c56f4784bf8674ab634769bb19))
* the list endpoints honour the role table instead of row ownership ([#205](https://github.com/amarkanday/experimentation-platform/issues/205)) ([77e150c](https://github.com/amarkanday/experimentation-platform/commit/77e150cfde006216abc9140c822accd65505f206))
* the pipeline owns the image the API service runs ([#209](https://github.com/amarkanday/experimentation-platform/issues/209)) ([3564c4f](https://github.com/amarkanday/experimentation-platform/commit/3564c4f1708c72ffbb285be1cab5e98a31a9c435))
* the production migration task bootstraps instead of replaying the alembic chain ([#182](https://github.com/amarkanday/experimentation-platform/issues/182)) ([7d78c64](https://github.com/amarkanday/experimentation-platform/commit/7d78c6405d7834c6f04b939e48ce51032c944de6))
* the trailing-slash redirect stays on the origin the client asked for ([#218](https://github.com/amarkanday/experimentation-platform/issues/218)) ([21a0fd4](https://github.com/amarkanday/experimentation-platform/commit/21a0fd4d8e5211f62661c738a568bca04eb9b944))


### Documentation

* add 12 new guides and update 5 existing docs across all phases ([7b0235c](https://github.com/amarkanday/experimentation-platform/commit/7b0235c3ba3301e665708856ede4cc70af5eeeee))
* **cut:** rewrite the launch checklist against the product that exists ([7015e16](https://github.com/amarkanday/experimentation-platform/commit/7015e169ab0b8365279978e3724406c36f644127))
* delete the marketing site's quickstart from the dashboard directory ([7bcc6b8](https://github.com/amarkanday/experimentation-platform/commit/7bcc6b8c09f34359ca63c607cb5fa70706852a4f))
* integration testing plan for EP-031 through EP-036 ([1a001d5](https://github.com/amarkanday/experimentation-platform/commit/1a001d5bb9bb209998b2404fd609076c116065d3))
* **readme:** state what CI asserts, not what a deployment would have measured ([a1716ee](https://github.com/amarkanday/experimentation-platform/commit/a1716ee01e8e93984c6d1a6a3f0f4ea15ce93657))
* record the three verification lessons from the P3.7 and [#79](https://github.com/amarkanday/experimentation-platform/issues/79) reviews ([#183](https://github.com/amarkanday/experimentation-platform/issues/183)) ([0af5d3f](https://github.com/amarkanday/experimentation-platform/commit/0af5d3f0b99a0f337dc03907876132cdd337dbdc))
* remove 33 redundant files for 30% reduction (111 → 78) ([afade50](https://github.com/amarkanday/experimentation-platform/commit/afade5086129adba28ad7219cfb1801f2c498081))
* tools that don't exist, 38 broken links, and 31 phantom API endpoints ([#296](https://github.com/amarkanday/experimentation-platform/issues/296)) ([9189b34](https://github.com/amarkanday/experimentation-platform/commit/9189b3480fa0a394ad9a00dc621b647a6db1cdd2))
