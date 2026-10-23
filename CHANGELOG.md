# Changelog

## [0.2.0](https://github.com/goatlabshq/goatbeat/compare/v0.1.0...v0.2.0) (2026-10-23)


### Features

* **django:** choose the task submitter with the GOATBEAT setting ([686f7c4](https://github.com/goatlabshq/goatbeat/commit/686f7c4db99a5a723e852365a226b2c29ca8afb7))


### Bug Fixes

* **django:** pass only libpq options to the notifier connection ([882f750](https://github.com/goatlabshq/goatbeat/commit/882f7509740bac8345deee19e7b75593b7ea62eb))
* **django:** release the lease after a single scheduler tick ([67d80be](https://github.com/goatlabshq/goatbeat/commit/67d80be9b93f0449ae44b51dbb2319c302f86af2))


### Documentation

* document the Celery prefork failure on Python 3.14 ([aeff4ae](https://github.com/goatlabshq/goatbeat/commit/aeff4aee82ddc9c1f443edfd8281a7144ae653e0))

## 0.1.0 (2026-10-19)


### Features

* **celery:** add the Celery submitter ([fe5d643](https://github.com/goatlabshq/goatbeat/commit/fe5d643ab30a3092a5c37f1f7d58a3a752b50bf2))
* **cli:** add the goatbeat command line ([91cd4bc](https://github.com/goatlabshq/goatbeat/commit/91cd4bcae1d48da3b612ad8d5b61c4c34aa0af0e))
* **core:** add cron expression parser ([5482a9f](https://github.com/goatlabshq/goatbeat/commit/5482a9f1bc3634ba4c7664c1ed3bce16eca25615))
* **core:** add interval trigger ([206eac7](https://github.com/goatlabshq/goatbeat/commit/206eac7dc8c432778ce178e4968374050387b119))
* **core:** add misfire policies ([85ca7a9](https://github.com/goatlabshq/goatbeat/commit/85ca7a9156caec00f6e3db8cfaf225775d2b694e))
* **core:** add requested runs and completion tracking ([0c0905f](https://github.com/goatlabshq/goatbeat/commit/0c0905f575766aeadb6628906346cd9e9e68eb0b))
* **core:** add scheduler loop and callable submitter ([d15a68a](https://github.com/goatlabshq/goatbeat/commit/d15a68ae9eaef5a8b74d07b0184aba44354c90cc))
* **core:** add SQLite development store ([e57a4b5](https://github.com/goatlabshq/goatbeat/commit/e57a4b5e7373f48262af5129639fe022725363cf))
* **core:** add store protocols, in-memory store and conformance suite ([8f90140](https://github.com/goatlabshq/goatbeat/commit/8f90140dc0870e0085180caabe1be936c217f654))
* **core:** add time, identifier and duration primitives ([b2788a0](https://github.com/goatlabshq/goatbeat/commit/b2788a0bc8c3e406855501facb6690239729ad08))
* **core:** add timezone-aware cron trigger ([cc011fc](https://github.com/goatlabshq/goatbeat/commit/cc011fcc10320eb47f4478e3f05900c938e60376))
* **core:** add typed configuration and observability hooks ([112a654](https://github.com/goatlabshq/goatbeat/commit/112a654ed3ebc8082ace4b87dadc86beb15b6d22))
* **core:** add typed task and schedule registry ([cd0b697](https://github.com/goatlabshq/goatbeat/commit/cd0b6973e71c2431866456b79b328038028127e4))
* **core:** describe the current lease and bundle an application ([e7201ad](https://github.com/goatlabshq/goatbeat/commit/e7201ad689e0cf83cd93f6064bde7acc4e54f71f))
* **core:** fan out metrics and release the lease on demand ([8da7c10](https://github.com/goatlabshq/goatbeat/commit/8da7c102b755ee40cb1a9a871262046f4108e92e))
* **django:** add models and migrations matching the PostgreSQL schema ([7862704](https://github.com/goatlabshq/goatbeat/commit/78627043f6faa9600de0b97737c41bed86659458))
* **django:** add settings, provider and typed schedule declarations ([d67d3ab](https://github.com/goatlabshq/goatbeat/commit/d67d3abed2a2057aa69ee1589b7b0539cdbdf8ce))
* **django:** add the goatbeat management command ([03f7efe](https://github.com/goatlabshq/goatbeat/commit/03f7efee3064fc5d69fec657d7d4e64d750dbd3f))
* **django:** add the schedule and execution admin ([026e720](https://github.com/goatlabshq/goatbeat/commit/026e7204c159424549ef320022e49963747b7df1))
* **django:** import django-celery-beat periodic tasks ([e3d9ca7](https://github.com/goatlabshq/goatbeat/commit/e3d9ca74e692defe296aa5e91a5188d79a37b8c7))
* **django:** submit through Django Tasks and track completion ([3fc973b](https://github.com/goatlabshq/goatbeat/commit/3fc973b391bdec9486cfe661ff9025b9e2d7b3f1))
* **dramatiq:** add the Dramatiq submitter ([3f58fb9](https://github.com/goatlabshq/goatbeat/commit/3f58fb9b9abf026ca39614854004a60566594a0c))
* expose backends, CLI and metrics from the facade ([a28b39c](https://github.com/goatlabshq/goatbeat/commit/a28b39c59164aa50648fc9a2bf99e36c7595ea72))
* expose public API from the goatbeat facade ([2f8ee66](https://github.com/goatlabshq/goatbeat/commit/2f8ee662d11458dc7ebfb2c0278ee23c04e9a271))
* expose the Django integration from the facade ([40efa30](https://github.com/goatlabshq/goatbeat/commit/40efa30e536e870c1c187d9c5f5f32f6ef32a99d))
* expose the PostgreSQL backend from the facade ([8ea2dc0](https://github.com/goatlabshq/goatbeat/commit/8ea2dc0bae6308fce1175adb7202f4ef5a594b27))
* **otel:** add the OpenTelemetry metrics sink ([68a6218](https://github.com/goatlabshq/goatbeat/commit/68a6218c7bff8bd4171cbc95e4d97b5ceafd192d))
* **postgres:** add PostgreSQL store and fenced lease ([ff06eb1](https://github.com/goatlabshq/goatbeat/commit/ff06eb1a6284e4ac5f5a272ef5127fce33315e20))
* **postgres:** add schema migrations and connection providers ([0b0c13e](https://github.com/goatlabshq/goatbeat/commit/0b0c13ea6138989b46b2fb4200c6c6c70a92985d))
* **postgres:** fail fast when the pool cannot connect ([a3620f5](https://github.com/goatlabshq/goatbeat/commit/a3620f5cfd9b70b6f1662df79479b0935978e5d6))
* **postgres:** report the applied schema version and the database clock ([9803f38](https://github.com/goatlabshq/goatbeat/commit/9803f386c4d67b669077e8ed54b9b2a59654aa85))
* **postgres:** wake schedulers with LISTEN/NOTIFY ([5e2bdda](https://github.com/goatlabshq/goatbeat/commit/5e2bdda0a23487c3019255d513ec52d104b298fa))
* **prometheus:** add the Prometheus metrics sink ([94128dd](https://github.com/goatlabshq/goatbeat/commit/94128ddeeacf2fcc779c339908371ab695897761))
* **rq:** add the RQ submitter ([fb67b8e](https://github.com/goatlabshq/goatbeat/commit/fb67b8e7ef72937a1eeed73847ff5aba82a56294))


### Bug Fixes

* apply completions that beat their dispatch record and align the Django schema ([2ded1ea](https://github.com/goatlabshq/goatbeat/commit/2ded1ea8b7ae01493251b02002af86a817202584))
* **ci:** claim every pending PyPI project before uploading ([5d56439](https://github.com/goatlabshq/goatbeat/commit/5d564394666ab29db546ecb1ba7195a12731988e))
* **ci:** publish without attestations from the reusable release workflow ([e348e17](https://github.com/goatlabshq/goatbeat/commit/e348e17c23e6d0aa4a47b15ad8389fe72d22dac3))
* **cli:** exit cleanly on schema, import, URL and unexpected errors ([bf4c895](https://github.com/goatlabshq/goatbeat/commit/bf4c8959b2fc71af45772adbcbd3adbee6fa99fe))
* **core:** find rare cron occurrences within the 400-year Gregorian cycle ([9698a38](https://github.com/goatlabshq/goatbeat/commit/9698a38878b5540155febcd920b62e5762628677))
* **core:** isolate broken schedules from the rest of the tick ([962227d](https://github.com/goatlabshq/goatbeat/commit/962227dbf6167b79f72d96310b7483e8491889fd))
* **core:** keep manual runs from hiding scheduled occurrences ([76ae6c5](https://github.com/goatlabshq/goatbeat/commit/76ae6c5632114bc6d2891cdf360a1c7bcb495e08))
* **core:** reject task arguments PostgreSQL cannot store ([7f54d93](https://github.com/goatlabshq/goatbeat/commit/7f54d93e1cfb5bbd724207daad689bb81219e005))
* **core:** retry scheduler startup while the store is down ([c7b7635](https://github.com/goatlabshq/goatbeat/commit/c7b76358b37f69d212d5212582e5606c0e835567))
* **core:** sleep on a monotonic deadline ([03298bf](https://github.com/goatlabshq/goatbeat/commit/03298bff5dd80e1c361578c52d364f5dd5b3ac01))
* **core:** validate configuration in the constructor ([a3b9532](https://github.com/goatlabshq/goatbeat/commit/a3b95323f9ba39eea9ea58f4a02a17889d8bb4ca))
* **django:** import celery-beat rows goatbeat cannot honor safely ([3876e55](https://github.com/goatlabshq/goatbeat/commit/3876e553a2e5c7ce93853d6c021edfcc797695d0))
* **django:** keep database options on the LISTEN connection ([66c47e1](https://github.com/goatlabshq/goatbeat/commit/66c47e16e15bbc776a5b990e52345e2756cf08e2))
* **django:** keep the schedule name when editing it in the admin ([8f1aefc](https://github.com/goatlabshq/goatbeat/commit/8f1aefc9574acc0bfa4e597e2bc4453a98237d4b))
* **django:** reject schedule targets that are not Django tasks ([5d2a42f](https://github.com/goatlabshq/goatbeat/commit/5d2a42fe75e48ad57979224ff9e82f67ded15592))
* **django:** report a task module that fails to import as an admin form error ([6107561](https://github.com/goatlabshq/goatbeat/commit/6107561b30b5d26d1b95322686269cf473deb913))
* **django:** require a PostgreSQL database for goatbeat ([ad4313b](https://github.com/goatlabshq/goatbeat/commit/ad4313bdc5a62db1bb42656ff5fd376eb40d964b))
* **django:** require change permission for schedule actions ([78b31dc](https://github.com/goatlabshq/goatbeat/commit/78b31dcd4144b56d4ecae3860db30b2bc8ff56e2))
* **django:** reuse healthy connections in the scheduler ([1742c42](https://github.com/goatlabshq/goatbeat/commit/1742c4237f32bdd96746945f32e0aad97980c21f))
* **dramatiq:** reject priorities the broker would ignore ([e111d78](https://github.com/goatlabshq/goatbeat/commit/e111d78ede98c14c1998a359ee658e2d5d2f6b4b))
* make the distributed example image build outside the workspace ([543e90e](https://github.com/goatlabshq/goatbeat/commit/543e90e3a938c53de5ce5a312b54f9032af1d125))
* **postgres:** bound lease lock waits and idle fence transactions ([6b4d19d](https://github.com/goatlabshq/goatbeat/commit/6b4d19daf9525f886848724693b1c50794cd7cd5))
* **postgres:** bound the notifier reconnect by the wait timeout ([c97678e](https://github.com/goatlabshq/goatbeat/commit/c97678ed011e35d0f4eca4d30de10fbbd2c532a4))
* **postgres:** never prepare statements so PgBouncer transaction mode works ([aac14a0](https://github.com/goatlabshq/goatbeat/commit/aac14a0aa3901a72594139d8ec9f496629f21fb0))
* **postgres:** refuse to run against a newer schema ([d2840a7](https://github.com/goatlabshq/goatbeat/commit/d2840a7cd2b792c8f2678ea49e9baa8d8bd3aec2))
* **postgres:** report unusable sessions as unavailable and harden the pool ([4373031](https://github.com/goatlabshq/goatbeat/commit/43730313fe4418f88c891244a7f615e4af70d697))
* **postgres:** serialize schedule writes so concurrent starts cannot conflict ([9b3cbb0](https://github.com/goatlabshq/goatbeat/commit/9b3cbb041e40098088be6000344a7ef829345089))
* schedule Celery tasks and Dramatiq actors by the name their workers resolve ([451eb7d](https://github.com/goatlabshq/goatbeat/commit/451eb7da1e8bd827e6bc6b6a402b6eade8ad4452))


### Performance Improvements

* **core:** bound misfire planning for catch-up and cron outages ([50fc767](https://github.com/goatlabshq/goatbeat/commit/50fc767953dafefe954d29c847b8e4c4a2e0a1b5))
* **core:** scan the DST window only near a transition ([90c3a45](https://github.com/goatlabshq/goatbeat/commit/90c3a457980f80d61dd4b2a385de842caf9da7cd))


### Documentation

* add a distributed compose example ([253fccc](https://github.com/goatlabshq/goatbeat/commit/253fccc7460635a269fe972d62797c02477a65de))
* add goatbeat design spec ([db89545](https://github.com/goatlabshq/goatbeat/commit/db89545cb984483d7e2531b994a260200dc811f0))
* add phase 1 implementation plan ([a90db20](https://github.com/goatlabshq/goatbeat/commit/a90db20a712e1a41d41dab290c58617ad44e5179))
* add phase 2 implementation plan ([8370ee9](https://github.com/goatlabshq/goatbeat/commit/8370ee952ba8fba1fa3d8bf2946779246c28b436))
* add phase 3 implementation plan ([bcf548f](https://github.com/goatlabshq/goatbeat/commit/bcf548ffc33f5f6dcff5378da43dd8620fc5c70c))
* add phase 4 implementation plan ([984a2d8](https://github.com/goatlabshq/goatbeat/commit/984a2d8e3b5c118bdcd66673201fdc98bf8327ca))
* add the documentation site ([52b3d13](https://github.com/goatlabshq/goatbeat/commit/52b3d13069332bd70e8755127c531637b0ac7d07))
* align documentation and example with actual behavior ([970f443](https://github.com/goatlabshq/goatbeat/commit/970f44325934cafc3c01b74b9ecab1edd4b73f75))
* **django:** show a LOGGING setup that keeps structured fields ([2ca05c2](https://github.com/goatlabshq/goatbeat/commit/2ca05c2b58d899a0c935681f84e0e647484a9278))
* document deduplication limits and command line conventions ([4ec492e](https://github.com/goatlabshq/goatbeat/commit/4ec492e5b0fbe2c27ea40758f1fe3510e665c8ae))
* document libpq, the PostgreSQL requirement and Celery and Dramatiq task paths ([81b0a69](https://github.com/goatlabshq/goatbeat/commit/81b0a695f86be3dfb5117e37977ae2635853bada))
* drop the superpowers exclusion from mkdocs ([fd894e2](https://github.com/goatlabshq/goatbeat/commit/fd894e27953d78ba994015da5626299a1fb70e38))
* format code samples with ruff ([d1d50b6](https://github.com/goatlabshq/goatbeat/commit/d1d50b63dc1108c1b8d06e5d8c47ff29391ff57e))
* publish llms.txt and llms-full.txt with mkdocs-llmstxt ([3df70bb](https://github.com/goatlabshq/goatbeat/commit/3df70bb0f1e6f1727cc43f04008529197c4d3c00))
