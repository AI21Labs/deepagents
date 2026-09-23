# Changelog

## [0.0.9](https://github.com/AI21Labs/deepagents/compare/deepagents-talon==0.0.8...deepagents-talon==0.0.9) (2026-09-23)


### Features

* **talon:** add /help command ([#6106](https://github.com/AI21Labs/deepagents/issues/6106)) ([919ad2b](https://github.com/AI21Labs/deepagents/commit/919ad2b56335c4e4cc416d474745efd78e0324a3))
* **talon:** add `send_message` for progress updates ([#6264](https://github.com/AI21Labs/deepagents/issues/6264)) ([15606d2](https://github.com/AI21Labs/deepagents/commit/15606d280a8ddb86c8966fef0bab257f8070944f))
* **talon:** add a current_time tool ([#6065](https://github.com/AI21Labs/deepagents/issues/6065)) ([0fe5f94](https://github.com/AI21Labs/deepagents/commit/0fe5f942d6359f956614584f37137bbba78ab589))
* **talon:** add channel debug logging ([#5983](https://github.com/AI21Labs/deepagents/issues/5983)) ([1c14626](https://github.com/AI21Labs/deepagents/commit/1c14626d068ee5e1724d53dc17927d37987ebe36))
* **talon:** add chat-scoped conversation history ([#6105](https://github.com/AI21Labs/deepagents/issues/6105)) ([d121141](https://github.com/AI21Labs/deepagents/commit/d12114143ec4ec15a04c5a7970c82899bf1b3caa))
* **talon:** add configurable conversation history storage ([#6115](https://github.com/AI21Labs/deepagents/issues/6115)) ([99fcef8](https://github.com/AI21Labs/deepagents/commit/99fcef85410736e211f5b0bcb2e9f1651e685105))
* **talon:** add configuration hardening self-review skill ([#6136](https://github.com/AI21Labs/deepagents/issues/6136)) ([e760662](https://github.com/AI21Labs/deepagents/commit/e760662c956c581a0aca2cd4c95a3a7ce2cbd187))
* **talon:** add Discord channel adapter ([#5992](https://github.com/AI21Labs/deepagents/issues/5992)) ([67c6c17](https://github.com/AI21Labs/deepagents/commit/67c6c17a316c84a6f21eafb95f12e56eedf11e7e))
* **talon:** add MCP configuration tools with default approval ([#6097](https://github.com/AI21Labs/deepagents/issues/6097)) ([f5f8dfe](https://github.com/AI21Labs/deepagents/commit/f5f8dfec051905befc83f65ff40100fd01ad2865))
* **talon:** add opt-in agent activity logging ([#5984](https://github.com/AI21Labs/deepagents/issues/5984)) ([3a0f68c](https://github.com/AI21Labs/deepagents/commit/3a0f68ccd08166394e02fd736869482be5759f83))
* **talon:** add optional hybrid conversation history search ([#6108](https://github.com/AI21Labs/deepagents/issues/6108)) ([904326a](https://github.com/AI21Labs/deepagents/commit/904326a7932f72a189fcf0a74ba1f77a4087f79f))
* **talon:** add targeted conversation deletion ([#6235](https://github.com/AI21Labs/deepagents/issues/6235)) ([4fb301d](https://github.com/AI21Labs/deepagents/commit/4fb301d647c860d0d8f2108149e58cd9fe623352))
* **talon:** add timezone-aware wall-clock cron schedules ([#6062](https://github.com/AI21Labs/deepagents/issues/6062)) ([afff4f8](https://github.com/AI21Labs/deepagents/commit/afff4f8841bcc370d01c2739f53e882a92ef5c6a))
* **talon:** authorize MCP servers through channels ([#6073](https://github.com/AI21Labs/deepagents/issues/6073)) ([76dd223](https://github.com/AI21Labs/deepagents/commit/76dd22334c95083449cc858dec245f98a383bba4))
* **talon:** batch concurrent tool approvals ([#6435](https://github.com/AI21Labs/deepagents/issues/6435)) ([1660147](https://github.com/AI21Labs/deepagents/commit/16601472424400ab4a90608d7d95e8fc61f23267))
* **talon:** interrupt active turns for new messages ([#6023](https://github.com/AI21Labs/deepagents/issues/6023)) ([f93752f](https://github.com/AI21Labs/deepagents/commit/f93752f855836b2af358a7c71c35a9f774af58e3))
* **talon:** keep typing indicator alive during long agent turns ([#5993](https://github.com/AI21Labs/deepagents/issues/5993)) ([e0d0afa](https://github.com/AI21Labs/deepagents/commit/e0d0afa18a3b8209f20c24cfda2ad766e476a102))
* **talon:** manage tool approvals through `tools.json` ([#6248](https://github.com/AI21Labs/deepagents/issues/6248)) ([a273ad6](https://github.com/AI21Labs/deepagents/commit/a273ad6c6a595c3aff915b744750711b50d544e3))
* **talon:** persist LangGraph checkpoints ([#6088](https://github.com/AI21Labs/deepagents/issues/6088)) ([337416a](https://github.com/AI21Labs/deepagents/commit/337416a85800818a5660afe8cfaedca16f8ac085))
* **talon:** register chat commands as Discord slash commands ([#6303](https://github.com/AI21Labs/deepagents/issues/6303)) ([f36b641](https://github.com/AI21Labs/deepagents/commit/f36b641ce3e1f44dbd47835d6dc9f5bb1c82324a))
* **talon:** reload MCP configuration without restarting ([#6084](https://github.com/AI21Labs/deepagents/issues/6084)) ([1ac5386](https://github.com/AI21Labs/deepagents/commit/1ac5386790ad2a069923161393410ef49a39a2b0))
* **talon:** reload subagent configuration on demand ([#6099](https://github.com/AI21Labs/deepagents/issues/6099)) ([bf78360](https://github.com/AI21Labs/deepagents/commit/bf78360c87725a3af546e97d03915fb64ecf13c0))
* **talon:** run a scheduled job's subagents inline ([#6425](https://github.com/AI21Labs/deepagents/issues/6425)) ([c3a041e](https://github.com/AI21Labs/deepagents/commit/c3a041e3d8f593e4e4c9bfc273d52264ceff165b))
* **talon:** run expendable subagents in the background ([#6098](https://github.com/AI21Labs/deepagents/issues/6098)) ([c7a4841](https://github.com/AI21Labs/deepagents/commit/c7a48414e90456bc6a453a3cbb60cc787221fc74))
* **talon:** ship defensive research defaults ([#6131](https://github.com/AI21Labs/deepagents/issues/6131)) ([1a835d2](https://github.com/AI21Labs/deepagents/commit/1a835d216260d3b140af528d42fbb75eca26f818))
* **talon:** support dcode-style subagents in fork mode ([#6085](https://github.com/AI21Labs/deepagents/issues/6085)) ([91bcf63](https://github.com/AI21Labs/deepagents/commit/91bcf63805c656fe0399aeaf9d25c0ae7f7a2cf2))
* **talon:** support fresh subagents and per-task tool selection ([#6129](https://github.com/AI21Labs/deepagents/issues/6129)) ([276a385](https://github.com/AI21Labs/deepagents/commit/276a385d6c49ef63f0cae107e5a1afa591191e03))
* **talon:** support GitHub MCP device authentication ([#6079](https://github.com/AI21Labs/deepagents/issues/6079)) ([d91ec7d](https://github.com/AI21Labs/deepagents/commit/d91ec7d0a7b8d0a703fa16b5ee4237c84d10526c))
* **talon:** support Slack MCP OAuth login ([#6078](https://github.com/AI21Labs/deepagents/issues/6078)) ([f8b137e](https://github.com/AI21Labs/deepagents/commit/f8b137ef22bf81f8178fe490f6dad7621f161a16))


### Bug Fixes

* **talon:** backfill missing research subagent defaults ([#6135](https://github.com/AI21Labs/deepagents/issues/6135)) ([54cf354](https://github.com/AI21Labs/deepagents/commit/54cf354d04d094eaf77c17ed239fdd235e4ebc83))
* **talon:** bound archive scans, query embeddings, and deletion markers ([#6162](https://github.com/AI21Labs/deepagents/issues/6162)) ([79c23e6](https://github.com/AI21Labs/deepagents/commit/79c23e669bf81cddf16e4ab1582ccc9b26d8bea7))
* **talon:** bound the vector rebuild, break the import cycle, pin postgres ([#6165](https://github.com/AI21Labs/deepagents/issues/6165)) ([8462c24](https://github.com/AI21Labs/deepagents/commit/8462c24524541f49a3eb53037580110586973c8c))
* **talon:** close a url swap past the MCP auto-approve guard ([#6173](https://github.com/AI21Labs/deepagents/issues/6173)) ([d886742](https://github.com/AI21Labs/deepagents/commit/d8867426af3ab83c31d64a11e5b84a21ce86a43d))
* **talon:** correct history embedding token budget and prompt defaults ([#6132](https://github.com/AI21Labs/deepagents/issues/6132)) ([caabca2](https://github.com/AI21Labs/deepagents/commit/caabca2b479ec731a81fa42e4c53c9471895fd7b))
* **talon:** declare the packages talon imports directly ([#6436](https://github.com/AI21Labs/deepagents/issues/6436)) ([c63eba4](https://github.com/AI21Labs/deepagents/commit/c63eba426b28f1d1685e40767f087dcc3f34334c))
* **talon:** deliver background subagents launched by a scheduled job ([#6228](https://github.com/AI21Labs/deepagents/issues/6228)) ([b6dc5c5](https://github.com/AI21Labs/deepagents/commit/b6dc5c5a8c6c1124f8e243868a83b9af188b08c7))
* **talon:** drop extract-zip from the WhatsApp bridge dependency tree ([#5924](https://github.com/AI21Labs/deepagents/issues/5924)) ([7301d01](https://github.com/AI21Labs/deepagents/commit/7301d01e483d0b76745c725134ec09db82f38856))
* **talon:** fix local voice transcription and embedding retries ([#6255](https://github.com/AI21Labs/deepagents/issues/6255)) ([a97ba32](https://github.com/AI21Labs/deepagents/commit/a97ba320fa797e9546efe3486ce703e8efd30fb4))
* **talon:** harden the MCP OAuth device flow and credential paths ([#6170](https://github.com/AI21Labs/deepagents/issues/6170)) ([e6c5829](https://github.com/AI21Labs/deepagents/commit/e6c58294d6792bcf433eb5f38fec1b5be70cc065))
* **talon:** improve channel reconnect resilience ([#6040](https://github.com/AI21Labs/deepagents/issues/6040)) ([54fe91f](https://github.com/AI21Labs/deepagents/commit/54fe91fd3745e285899961bfe74380c837674164))
* **talon:** index only visible conversation text ([#6358](https://github.com/AI21Labs/deepagents/issues/6358)) ([f6850e9](https://github.com/AI21Labs/deepagents/commit/f6850e9d25854b5679010c08f02adae99e6b8a2c))
* **talon:** keep results a discarded turn never reported ([#6231](https://github.com/AI21Labs/deepagents/issues/6231)) ([481773c](https://github.com/AI21Labs/deepagents/commit/481773caed336c86034e1c72b4988e7e93968610))
* **talon:** keep the cron ticker alive through a failed tick ([#6087](https://github.com/AI21Labs/deepagents/issues/6087)) ([4c062ec](https://github.com/AI21Labs/deepagents/commit/4c062ec76e2cf19abb3ac8a78b1bf68cf7ece3cd))
* **talon:** make background subagents and host start/stop recoverable ([#6166](https://github.com/AI21Labs/deepagents/issues/6166)) ([d4c41b0](https://github.com/AI21Labs/deepagents/commit/d4c41b048132eb27e2337b60b21463403b615390))
* **talon:** make MCP configuration updates bounded and non-destructive ([#6171](https://github.com/AI21Labs/deepagents/issues/6171)) ([f995931](https://github.com/AI21Labs/deepagents/commit/f9959311bfeb788191f971fe32552b01adbac199))
* **talon:** make remote embedding settings explicit and search non-blocking ([#6133](https://github.com/AI21Labs/deepagents/issues/6133)) ([3698f10](https://github.com/AI21Labs/deepagents/commit/3698f10bc46ef6ac6d7b30c1fcdc499a8ac08b28))
* **talon:** make subagent orchestration state what it enforces ([#6167](https://github.com/AI21Labs/deepagents/issues/6167)) ([05620cc](https://github.com/AI21Labs/deepagents/commit/05620cc72bfa7b81ce41064641cfa5808cb7c74a))
* **talon:** migrate MCP discovery to `discover_mcp_config_sources` ([#5803](https://github.com/AI21Labs/deepagents/issues/5803)) ([5cdd977](https://github.com/AI21Labs/deepagents/commit/5cdd97730708b0480cb7d32792717dcdcd02f4ea))
* **talon:** normalize OAuth TLS server hostname ([#6102](https://github.com/AI21Labs/deepagents/issues/6102)) ([34005a4](https://github.com/AI21Labs/deepagents/commit/34005a4efab0ab2ee2466fec413844ddae0b27c1))
* **talon:** omit empty optional MCP arguments ([#6077](https://github.com/AI21Labs/deepagents/issues/6077)) ([632f2c9](https://github.com/AI21Labs/deepagents/commit/632f2c941b877eff70407606b58e393212448a26))
* **talon:** persist history vector deduplication ([#6357](https://github.com/AI21Labs/deepagents/issues/6357)) ([b3d4967](https://github.com/AI21Labs/deepagents/commit/b3d4967bdcda5b42e976b3e97c357deea82d63ac))
* **talon:** persist local model downloads ([#6137](https://github.com/AI21Labs/deepagents/issues/6137)) ([fc91199](https://github.com/AI21Labs/deepagents/commit/fc91199a44b99990cca49341169aea858da222fc))
* **talon:** persist OAuth token expiry ([#6090](https://github.com/AI21Labs/deepagents/issues/6090)) ([a02d2df](https://github.com/AI21Labs/deepagents/commit/a02d2df874332784530082261f801512bbf62dee))
* **talon:** preserve WhatsApp approval loops and handle reactions ([#6104](https://github.com/AI21Labs/deepagents/issues/6104)) ([eca6203](https://github.com/AI21Labs/deepagents/commit/eca6203338a4d7927456ff1ec70b3a29f01e9799))
* **talon:** preserve WhatsApp quoted message context ([#6025](https://github.com/AI21Labs/deepagents/issues/6025)) ([03436b3](https://github.com/AI21Labs/deepagents/commit/03436b369c0324498602fe6b7918cf36f3629d76))
* **talon:** report Discord gateway failures after startup ([#6113](https://github.com/AI21Labs/deepagents/issues/6113)) ([94e4520](https://github.com/AI21Labs/deepagents/commit/94e452077cf2650b0a410da7fa1e23b28d5dd8e1))
* **talon:** report MCP protocol errors to the model ([#6239](https://github.com/AI21Labs/deepagents/issues/6239)) ([edd0bcf](https://github.com/AI21Labs/deepagents/commit/edd0bcfc61dc16eabea0b3a59aa84569e3b240dc))
* **talon:** restore WhatsApp bridge compatibility ([#5999](https://github.com/AI21Labs/deepagents/issues/5999)) ([568b398](https://github.com/AI21Labs/deepagents/commit/568b398df9b9f4f3464b4107c0ef9001f530d728))
* **talon:** restrict WhatsApp replies to self-chat ([#6010](https://github.com/AI21Labs/deepagents/issues/6010)) ([40359ec](https://github.com/AI21Labs/deepagents/commit/40359ec683eaff3a67b39d3f6b3003e70db9ec4d))
* **talon:** retry statusless provider overload errors ([#6304](https://github.com/AI21Labs/deepagents/issues/6304)) ([f8acbd0](https://github.com/AI21Labs/deepagents/commit/f8acbd0ae24278d35aeb1fa014056084a58f70d2))
* **talon:** secure OAuth discovery and restart token refresh ([#6100](https://github.com/AI21Labs/deepagents/issues/6100)) ([43c2994](https://github.com/AI21Labs/deepagents/commit/43c299460042b8ae44b2162fba24be456088bdb9))
* **talon:** share one optional-driver loader and close provider clients ([#6164](https://github.com/AI21Labs/deepagents/issues/6164)) ([02cea21](https://github.com/AI21Labs/deepagents/commit/02cea210d7f3e5bc2bf89453e8a6e4af59031f59))
* **talon:** stop HistoryEmbeddings defaulting to Qwen's query prefix ([#6134](https://github.com/AI21Labs/deepagents/issues/6134)) ([933d863](https://github.com/AI21Labs/deepagents/commit/933d86350f0d0ffa54359d4f00510e52ccdc2b85))
* **talon:** stop losing MCP refresh tokens on a refresh response ([#6172](https://github.com/AI21Labs/deepagents/issues/6172)) ([7dc07cb](https://github.com/AI21Labs/deepagents/commit/7dc07cbb60f144e2b7fc266ee452b06c8b8dd10c))
* **talon:** stop one conversation from stalling or outliving the rest ([#6168](https://github.com/AI21Labs/deepagents/issues/6168)) ([134ffc7](https://github.com/AI21Labs/deepagents/commit/134ffc7bb4eba504ee90aaae3a70df87c6ea3217))
* **talon:** surface indexing failures and bound the indexing worker ([#6163](https://github.com/AI21Labs/deepagents/issues/6163)) ([03653d6](https://github.com/AI21Labs/deepagents/commit/03653d6d95ceb0b1b6739998fd9475e304489d12))
* **talon:** treat trailing [SILENT] as a suppression marker ([#6110](https://github.com/AI21Labs/deepagents/issues/6110)) ([92576da](https://github.com/AI21Labs/deepagents/commit/92576daf1cfaadfc811445b29be9457a78eb4e5e))
* **talon:** unwind the channel that fails mid-start, and keep teardown safe ([#6169](https://github.com/AI21Labs/deepagents/issues/6169)) ([5406820](https://github.com/AI21Labs/deepagents/commit/5406820ec1c00ce521b0f54bb786c511da092f01))
* **talon:** validate archive pagination arguments ([#6442](https://github.com/AI21Labs/deepagents/issues/6442)) ([f84d963](https://github.com/AI21Labs/deepagents/commit/f84d96358a111872fba3f9b69c5b08ad1565c083))


### Performance Improvements

* **talon:** reduce archive replay transactions ([#6320](https://github.com/AI21Labs/deepagents/issues/6320)) ([89bd48f](https://github.com/AI21Labs/deepagents/commit/89bd48f7d531c9affafa3f0dc096083cbc5969dd))
* **talon:** store cron jobs in a structured, versioned format ([#6086](https://github.com/AI21Labs/deepagents/issues/6086)) ([4e5f935](https://github.com/AI21Labs/deepagents/commit/4e5f9350e4d77b8bf19e472e8414662d3fa59dc0))

## [0.0.8](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.7...deepagents-talon==0.0.8) (2026-09-11)

### Features

- Added `send_message` support for progress updates. ([#6264](https://github.com/langchain-ai/deepagents/pull/6264))
- Added targeted conversation deletion. ([#6235](https://github.com/langchain-ai/deepagents/pull/6235))
- Added support for managing tool approvals through `tools.json`. ([#6248](https://github.com/langchain-ai/deepagents/pull/6248))

### Bug Fixes

- Improved MCP reliability and safety by hardening OAuth device-flow and credential handling, preserving refresh tokens, making configuration updates bounded and non-destructive, reporting protocol errors to the model, and preventing URL swaps past the auto-approve guard. ([#6170](https://github.com/langchain-ai/deepagents/pull/6170), [#6172](https://github.com/langchain-ai/deepagents/pull/6172), [#6171](https://github.com/langchain-ai/deepagents/pull/6171), [#6239](https://github.com/langchain-ai/deepagents/pull/6239), [#6173](https://github.com/langchain-ai/deepagents/pull/6173))
- Improved background subagent and conversation reliability, including recoverable start/stop behavior, scheduled-job delivery, clearer orchestration enforcement, preventing one conversation from stalling or outliving the rest, and suppressing results from discarded turns. ([#6166](https://github.com/langchain-ai/deepagents/pull/6166), [#6228](https://github.com/langchain-ai/deepagents/pull/6228), [#6167](https://github.com/langchain-ai/deepagents/pull/6167), [#6168](https://github.com/langchain-ai/deepagents/pull/6168), [#6231](https://github.com/langchain-ai/deepagents/pull/6231))
- Improved indexing and vector maintenance by bounding archive scans, query embeddings, deletion markers, vector rebuilds, and indexing workers, while surfacing indexing failures and resolving import-cycle and PostgreSQL dependency issues. ([#6162](https://github.com/langchain-ai/deepagents/pull/6162), [#6165](https://github.com/langchain-ai/deepagents/pull/6165), [#6163](https://github.com/langchain-ai/deepagents/pull/6163))
- Fixed local voice transcription and embedding retries, and ensured local model downloads persist. ([#6255](https://github.com/langchain-ai/deepagents/pull/6255), [#6137](https://github.com/langchain-ai/deepagents/pull/6137))
- Improved startup, teardown, and provider cleanup by safely unwinding channels that fail mid-start, sharing the optional-driver loader, and closing provider clients. ([#6169](https://github.com/langchain-ai/deepagents/pull/6169), [#6164](https://github.com/langchain-ai/deepagents/pull/6164))

## [0.0.7](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.6...deepagents-talon==0.0.7) (2026-09-07)

### Highlights

- Added Discord channel support, including improved gateway failure reporting after startup. ([#5992](https://github.com/langchain-ai/deepagents/issues/5992), [#6113](https://github.com/langchain-ai/deepagents/issues/6113))
- Added chat-scoped conversation history with configurable storage and optional hybrid search. ([#6105](https://github.com/langchain-ai/deepagents/issues/6105), [#6115](https://github.com/langchain-ai/deepagents/issues/6115), [#6108](https://github.com/langchain-ai/deepagents/issues/6108))
- Added MCP configuration tools, channel-based MCP server authorization, hot reload for MCP configuration, and OAuth/device authentication support for Slack and GitHub MCP integrations. ([#6097](https://github.com/langchain-ai/deepagents/issues/6097), [#6073](https://github.com/langchain-ai/deepagents/issues/6073), [#6084](https://github.com/langchain-ai/deepagents/issues/6084), [#6078](https://github.com/langchain-ai/deepagents/issues/6078), [#6079](https://github.com/langchain-ai/deepagents/issues/6079))
- Added more flexible subagent execution, including background expendable subagents, dcode-style subagents in fork mode, fresh subagents, per-task tool selection, and on-demand subagent configuration reloads. ([#6098](https://github.com/langchain-ai/deepagents/issues/6098), [#6085](https://github.com/langchain-ai/deepagents/issues/6085), [#6129](https://github.com/langchain-ai/deepagents/issues/6129), [#6099](https://github.com/langchain-ai/deepagents/issues/6099))
- Added defensive research defaults and a configuration-hardening self-review skill, with missing research subagent defaults backfilled. ([#6131](https://github.com/langchain-ai/deepagents/issues/6131), [#6136](https://github.com/langchain-ai/deepagents/issues/6136), [#6135](https://github.com/langchain-ai/deepagents/issues/6135))

### New features

- Added a `/help` command. ([#6106](https://github.com/langchain-ai/deepagents/issues/6106))
- Added a `current_time` tool and timezone-aware wall-clock cron schedules. ([#6065](https://github.com/langchain-ai/deepagents/issues/6065), [#6062](https://github.com/langchain-ai/deepagents/issues/6062))
- Added persistent LangGraph checkpoints. ([#6088](https://github.com/langchain-ai/deepagents/issues/6088))
- Added channel debug logging and opt-in agent activity logging. ([#5983](https://github.com/langchain-ai/deepagents/issues/5983), [#5984](https://github.com/langchain-ai/deepagents/issues/5984))
- New messages can now interrupt active turns. ([#6023](https://github.com/langchain-ai/deepagents/issues/6023))
- Long agent turns now keep the typing indicator alive. ([#5993](https://github.com/langchain-ai/deepagents/issues/5993))

### Fixes and improvements

- Improved channel reconnect resilience. ([#6040](https://github.com/langchain-ai/deepagents/issues/6040))
- Improved cron reliability by keeping the ticker alive after failed ticks, and stored cron jobs in a structured, versioned format. ([#6087](https://github.com/langchain-ai/deepagents/issues/6087), [#6086](https://github.com/langchain-ai/deepagents/issues/6086))
- Improved conversation history embeddings and search by correcting token budgets and prompt defaults, making remote embedding settings explicit, keeping search non-blocking, and removing the default Qwen query prefix. ([#6132](https://github.com/langchain-ai/deepagents/issues/6132), [#6133](https://github.com/langchain-ai/deepagents/issues/6133), [#6134](https://github.com/langchain-ai/deepagents/issues/6134))
- Fixed OAuth and MCP integration issues, including TLS hostname normalization, omitted empty optional MCP arguments, persisted OAuth token expiry, secured OAuth discovery, and restarted token refresh. ([#6102](https://github.com/langchain-ai/deepagents/issues/6102), [#6077](https://github.com/langchain-ai/deepagents/issues/6077), [#6090](https://github.com/langchain-ai/deepagents/issues/6090), [#6100](https://github.com/langchain-ai/deepagents/issues/6100))
- Fixed WhatsApp behavior by restoring bridge compatibility, preserving quoted message context and approval loops, handling reactions, and restricting replies to self-chat. ([#5999](https://github.com/langchain-ai/deepagents/issues/5999), [#6025](https://github.com/langchain-ai/deepagents/issues/6025), [#6104](https://github.com/langchain-ai/deepagents/issues/6104), [#6010](https://github.com/langchain-ai/deepagents/issues/6010))
- Treated trailing `[SILENT]` as a suppression marker. ([#6110](https://github.com/langchain-ai/deepagents/issues/6110))

## [0.0.6](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.5...deepagents-talon==0.0.6) (2026-08-28)

### Bug Fixes

- Removed `extract-zip` from the WhatsApp bridge dependency tree. ([#5924](https://github.com/langchain-ai/deepagents/issues/5924))

## [0.0.5](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.4...deepagents-talon==0.0.5) (2026-08-26)

### Bug Fixes

- Migrated MCP discovery to `discover_mcp_config_sources`. ([#5803](https://github.com/langchain-ai/deepagents/issues/5803))

## [0.0.4](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.3...deepagents-talon==0.0.4) (2026-08-24)

### Features

- Require Python 3.12 or greater. ([#5603](https://github.com/langchain-ai/deepagents/issues/5603))

## [0.0.3](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.2...deepagents-talon==0.0.3) (2026-07-06)


### Features

* **sdk:** optional video frame extraction on `read_file` ([#4094](https://github.com/langchain-ai/deepagents/issues/4094)) ([b927147](https://github.com/langchain-ai/deepagents/commit/b927147d026749c6c790bb06c9853515dabf579c))
* **talon:** add Fleet zip import command ([#4493](https://github.com/langchain-ai/deepagents/issues/4493)) ([0289dd0](https://github.com/langchain-ai/deepagents/commit/0289dd0a190e5060e631e840da115dd59c64cf5c))


### Bug Fixes

* **talon:** materialize agents under home ([f2b26a8](https://github.com/langchain-ai/deepagents/commit/f2b26a8915fb70c26d32af6e8240442e5e6118e6))

## [0.0.2](https://github.com/langchain-ai/deepagents/compare/deepagents-talon==0.0.1...deepagents-talon==0.0.2) (2026-06-30)


### Features

* **talon:** `DEEPAGENTS_TALON_RECURSION_LIMIT` env var ([#4354](https://github.com/langchain-ai/deepagents/issues/4354)) ([82d1eac](https://github.com/langchain-ai/deepagents/commit/82d1eac59a43f096096e86849733aa716adb18fc))
* **talon:** add reaction approval routing ([#4345](https://github.com/langchain-ai/deepagents/issues/4345)) ([3fe8c0c](https://github.com/langchain-ai/deepagents/commit/3fe8c0c35536626f583df08573469506b9529706))
* **talon:** add Telegram channel adapter, CLI wiring, and offset persistence ([#4097](https://github.com/langchain-ai/deepagents/issues/4097)) ([7c87cec](https://github.com/langchain-ai/deepagents/commit/7c87ceca069874db8555705efab3973301baa1cb))
* **talon:** add tool approval env override ([#4349](https://github.com/langchain-ai/deepagents/issues/4349)) ([d26481d](https://github.com/langchain-ai/deepagents/commit/d26481da615881bae4401dfa485ad925945e667a))
* **talon:** audit reaction approval attempts ([#4348](https://github.com/langchain-ai/deepagents/issues/4348)) ([d7895c4](https://github.com/langchain-ai/deepagents/commit/d7895c4f9b996ad6fe194936bbeaa8beea21e913))
* **talon:** ingest Telegram approval reactions ([#4346](https://github.com/langchain-ai/deepagents/issues/4346)) ([437af0b](https://github.com/langchain-ai/deepagents/commit/437af0bf79332b20ae0c1883c3cc4d91a98c2457))


### Bug Fixes

* **talon:** default workspace to current directory ([#4099](https://github.com/langchain-ai/deepagents/issues/4099)) ([5e337ae](https://github.com/langchain-ai/deepagents/commit/5e337ae50a76bc174b752be187e62698a389cbe6))

## Changelog

All notable changes to this project will be documented in this file.
