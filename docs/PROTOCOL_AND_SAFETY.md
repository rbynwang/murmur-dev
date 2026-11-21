# Protocol and safety

How Murmur's participants exchange signed messages over the message bus, and the chain of checks that stands between a model, a device and a payment. This specifies the code in `src/murmur`, `demo/runner` and `tests` as it is.

**Settings.** A participant's settings are `config.DEFAULTS`, then the dataset's `agent_defaults` in `dataset.json`, then its own `agent.json`; a value in `agent.json` equal to the built-in default yields to the dataset's. `agent.json` and `secrets/` sit in `$MURMUR_CONFIG_DIR` (else `.config/murmur` in the home folder). The code also reads `MURMUR_DATA_DIR`, `MURMUR_MODELS_DIR`, `MURMUR_LOG_DIR` (else `logs/` in the configuration folder), `MURMUR_DRIVERS`, `MURMUR_CAREFUL_NOTES`, `MURMUR_DEVICES`, `MURMUR_BATTERY_MODE`, `MURMUR_CHARGE_KW` and `MURMUR_LEAD_MIN`.

**Addresses.** Every address a participant listens on or calls is a setting. Every service listens at `bind_host` (`config.DEFAULTS`: `127.0.0.1`, the loopback address), at the port a setting names: `host_port`, `buildings_port`, `community_port`, `aggregator_port`, `site_port`, and `--port` for a stand-in buyer. What a participant calls: the bus (`town_url`), the model server (`llm_url`, read only with `llm_enabled`, off by default), and for the community's clock the first buyer (`utility_url`), the homes' host (`host_url`), each building (`building_urls`) and the other clocks (`clock_extra_targets`). The runner (`demo/runner`) gives every part its configuration's `host` (`127.0.0.1` when none is given) as `bind_host`, starts its bus and stand-in model there (`--host`), serves its state feed there, and builds every address it hands out on that host; only the node hosts get a model's address, and every other part has no `llm_url`.

| Concern | Code |
|---|---|
| Envelope, signing, message ids, wire log | `src/murmur/protocol/envelope.py`, `signing.py`, `ids.py`, `wire.py` |
| Bus client, inbox polling | `src/murmur/protocol/transport.py`, `inbox.py` |
| Control token on the participants' services | `src/murmur/protocol/doors.py` |
| Local bus, run grants | `demo/runner/bus.py`, `demo/runner/grants.py` |
| What may leave a member node, readings, batches | `src/murmur/node/amount.py`, `home_delivery.py`, `report_rule.py` |
| Real-time desk | `src/murmur/agents/community/gaps.py`, `gaps_calls.py`, `demo/runner/buyers/grid_watch.py` |
| Aggregator, single site | `src/murmur/agents/aggregator.py`, `site_service.py` |
| Model client, fixed modes, notes, reports | `src/murmur/node/llm_client.py`, `modes.py`, `note_reader.py`, `note_words.py`, `agent_notes.py`, `report.py` |
| One device call: step, arguments, policy, guard, seal, driver | `src/murmur/node/context.py`, `calls.py`, `policy.py`, `guard.py`, `guard_building.py`, `guard_building_rules.py`, `guard_building_tools.py`, `drivers.py` |
| Alarm hold, a person's signed word | `src/murmur/node/person.py`, `policy.py` (`OwnerChannel`), `src/murmur/agents/host_people.py` |
| Reading checks, settlement | `src/murmur/settlement/meter_check.py`, `market_checks.py`, `rules.py` |

## Part 1. Protocol

### 1. The envelope

`envelope.make(action, *, sender, receiver, transaction_id, message, key, sender_role="bap", message_id=None, ttl_s=None, wall=None)` builds and signs one body:

```json
{"context": {...}, "message": {...}, "signer": "<64 hex>", "sig": "<128 hex>"}
```

| Context field | Value |
|---|---|
| `networkId` | `murmur.local/demo-deg` (`NETWORK`) |
| `version`, `domain` | `2.0.0`, `beckn.one:deg:demand-flex:2.0.0` |
| `action` | one of the actions below |
| `bapId`, `bppId` | the sender fills `bapId` with `sender_role="bap"` and `bppId` with `"bpp"`; the receiver fills the other. Members, buyers, single sites and a community's messages upward send as `bpp` |
| `transactionId` | the conversation the message belongs to |
| `messageId` | the id the sender passes, else a new UUID4 |
| `timestamp` | UTC, `YYYY-MM-DDTHH:MM:SSZ`, of the moment the body is made, or of `wall` when given |
| `ttl` | ISO 8601 duration, `PT<n>S` |
| `sentWall` | the sender's wall clock, in seconds, when it made the body, or `wall` when given. `wall=0.0` makes a body that never expires; only tests pass `wall` |

The message goes through JSON before it is signed, so what is signed is exactly what arrives: an integer key becomes a string.

| Phase | Actions |
|---|---|
| Day ahead | `discover`/`on_discover`, `select`/`on_select`, `init`/`on_init`, `confirm`/`on_confirm`, `cancel`, `update`, `status`/`on_status` |
| During the day | `rt_call`, `rt_end`, `rt_ask`/`rt_answer`, `rt_dispatch`, `rt_confirm`, `rt_capacity` (section 5) |
| Community and aggregator | `request` (bus kind `community.request`), `on_request` (`community.answer`), `report` (`community.report`) |

A market message's bus kind is `beckn.<action>` (`envelope.kind`; `action_of` strips the prefix).

**Time to live.** `TTL_S` is 900 s, for requests and answers that matter only while the market decides. `TTL_EVIDENCE_S` is 86 400 s, for statements of fact: a signed reading, a batch of readings, a chase for a sale's missing readings, the "readings are in" notice, a buyer's status replies (baselines, actuals, a settlement, what it lacks), a payment notice, and the answers and report rows a community or a single site sends upward. `ttl_seconds` reads `P[nD][T[nH][nM][nS]]`; anything else takes the default. `expired(body, now_wall=None, default_ttl=TTL_S)` is how many seconds a body is past `sentWall + ttl`, or `None` while it is valid; a body without a positive numeric `sentWall` never expires. Three receivers check it, with `max_message_age_s` (default 900) for a `ttl` that can't be read: a member answers `Refused("expired <n> s ago: not acted on")`, the stand-in buyer `Refused("expired: not acted on")`, and the community service acknowledges `rejected` with `{"skipped": "expired", "late_s": n}`. The aggregator and a single site never check expiry, and a quiet member answers a chase for readings before its expiry check runs. The stand-in buyer also refuses any body sent before its current run started, and the community market ignores a reading sent before its run.

**What a member may say.** Every market message a member makes itself passes `amount.only(action, message)` (`MemberNode.say`): only the fields listed for that action (`ALLOWED`) leave the node, and only plain values, a number, a boolean, null, a string without whitespace or a `YYYY-MM-DD HH:MM` time, so no sentence fits through. An unlisted action carries `{}`. Before a reason is dropped, `only` turns the one thing the market reads in it into a flag: an `rt_capacity` whose reason is `the forecast changed` gets `drift: true`, and an `rt_answer` whose why mentions a price gets `below_min_price: true`. A commitment's answer carries `id`, `event_id`, `home` and `status`, never its reason; an `rt_answer` carries `id`, `kw` and `below_min_price`; an `rt_capacity` carries `short` (kW by quarter hour), `abnormal` and `drift`; a reading carries the fields of section 4; a report carries numbers only (section 13). A dropped field that is not on the `NOT_NEEDED` list is logged as `wire_kept_back`. A quiet member's batch envelope (`{"batch": [...]}`, section 4) is made by `envelope.make` directly and never passes `only`, which would drop `batch`; only the readings inside it did.

**The wire log.** With a log path open, `wire.note` appends one JSON line per signed message: `t` (the wall time it was written), direction, sender, receiver, action, whether it checked out, the dataset time, the message id, the first 16 hex characters of signer and signature, `sentWall`, and the message. In the log folder the community keeps `town_wire.jsonl` (what it sends and receives), the aggregator `town_wire_aggregator.jsonl` (its requests and what it receives), each single site `town_wire_<name>.jsonl` (what it sends) and each stand-in buyer `town_wire_<name>.jsonl` (the readings it receives). Node hosts keep none.

### 2. Canonical JSON and Ed25519 signing

- `canonical(obj)` is `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, so key order and spacing never change a signature.
- `sign(payload, key)` drops any `sig`, sets `signer` to the raw Ed25519 public key in hex, and adds `sig`, the Ed25519 signature over the canonical form of everything else. Every envelope and every reading is signed this way, and so is a person's word (`policy.signed`).
- `verify(payload, public)` holds only when the body has a `sig`, its `signer` equals `public`, and the signature verifies over the canonical form. A changed field, a swapped signer or a missing signature fails.
- Each receiver checks a sender against one key. Members, a community whose definition gives its aggregator's key, an aggregator whose list gives a key, and a single site hold that key beforehand. Every other receiver trusts on first use: the community market and the stand-in buyer pin the `signer` of the sender's first message, the aggregator the `signer` of the first message that verifies under it, and each checks every later message against that key:

| Receiver | Key it checks a sender against |
|---|---|
| Member node | the bus sender must be `community` (the name the hosts give every member's community), and the body's `signer` one of `community_pubkeys` in the host's `agent.json`, read again at each check, or the host's own key when its role is `community` |
| Community market | the key pinned at the sender's first message, member or buyer, kept in `state/home_pins.json` |
| Community, from its aggregator | the key its community definition gives, else the key pinned at first contact; the sender must be the aggregator on record and `bapId`/`bppId` must name the two |
| Stand-in buyer | the key pinned at the sender's first message; contract steps only from `utility_aggregators` (default `["community"]`), and a reading must name its sender as `home`. In a batch it checks each reading, never the envelope, and reads a batch inside a batch as one more batch |
| Aggregator stand-in | the key its community list gives, else the key of the first message that verifies under its own `signer`, pinned then (a message that fails pins nothing); `bppId` must name the sender and `bapId` the aggregator |
| Single site | `site_aggregator.public_key`, never pinned; it takes only `community.request`, only from `site_aggregator.name`, with `bapId`/`bppId` naming the two |

- `load_or_create(path)` keeps one Ed25519 private key per file, the 32 raw bytes in hex. A new key is written to a temporary file of mode 600, synced, and hard-linked into place; the link fails if the name is taken, so processes that start at once end on one key. A host keeps one key per member in `fleet/keys/<name>.key` of its configuration folder.

### 3. Message ids

One logical message has one id, so a retry, a redelivery or a resend names it again and the bus takes it once.

- **Plain form.** `message_id(scope, sender, to, kind, *key)` joins its parts with `:`, `kind` without `beckn.`. The aggregator's request is `<aggregator>:<community>:request:<id>`, a single site's answer `<site>:<aggregator>:on_request:<id>` and its report row `<site>:<aggregator>:report:<site id>:<timestamp>`, all plain.
- **Sealed id**, for a message nobody asked for (a reading, a batch, a broadcast, a report row upward, the community's answer to its aggregator): `sealed(key, scope, ...)` appends `:` and `signing.seal(key, plain)`, the first 16 hex characters of HMAC-SHA256 over the plain id, keyed with the SHA-256 of `murmur ids:` and the raw private key. The same key names a message the same way every time, and nobody without the key can name it first. The scope is the sender's play, an 8-hex tag (`new_play`) made when the sender starts and again at each reset (`/demo/start`, `/demo/reset`), so a new run never names a message of the last one. The play is held in memory: a restarted sender names its unasked messages under a new play.
- **Asked id**, for an answer: `asked(body)` is `a` and the `digest` of the question's `context.messageId`, or of the whole body when it has none. `digest(*parts)` is the first 10 hex characters of SHA-1 over `json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)`, ASCII-escaped, unlike `canonical`. A member's answers, a quiet member's answer to a chase and the stand-in buyer's replies to a question go under that scope, unsealed: the same however often the bus hands the question out, and new when the asker asks again under a new message id.
- **A batch**: `readings(bodies)` is the digest of the sorted `(contract_id, slot_id)` pairs in it, so the same half hours in any order are the same batch.

A member's reading is `<play>:home-01:community:on_status:<contract>:<slot>:<seal>`, its batch `<play>:home-01:community:on_status:readings:<digest>:<seal>`, and its offer, an answer, `a<digest>:home-01:community:on_discover:<event>`.

### 4. Readings and batches

A member sends one signed reading for each half hour it owes once both 15-minute meter rows of it are in. `message.performance`:

| Field | Meaning |
|---|---|
| `contract_id`, `event_id`, `home`, `slot_id`, `start` | the half hour: contract, sale, sender, slot (an integer), local start |
| `committed_kw` | what the contract asks in it |
| `usage_kw` | mean grid import over it (export is negative) |
| `battery_kw` | mean battery and car-to-home output |
| `pre_kw` | mean import in the hour that starts 2 h before the window (the same-day adjustment), or null |
| `truth` | the simulator's `usage_without_event_kw` and `delivered_true_kw`; left out of the copy to the meter owner |

The class that speaks for a member is `host_common.node_class`: `MemberNode` when the setting `buyers` is empty and `report_rule` is not `exception`, `PoolNode` with `buyers`, `QuietNode` with `report_rule` = `exception`, which the runner sets.

A `MemberNode` or `PoolNode` sends each reading to the community and, signed separately, to the meter owner (`utility_name`, default `utility`), both with `TTL_EVIDENCE_S`. A half hour counts as reported only when both sends went through; until then it is due again at the next tick.

A `QuietNode` hands its readings to an `Outbox`, which holds them, one list per receiver, and a half hour counts as reported once it is held. Each list goes as one envelope `{"batch": [reading bodies]}`, signed by the member, with `TTL_EVIDENCE_S` and transaction `readings-<name>`: 45 min of dataset time (`HOLD_MIN`) after the last reading came in, or 225 min (`MAX_HOLD_MIN`) after the first. The tick never makes a batch again: the node host's retries (section 8) and the community's chases recover a lost one. A chase (`status` with `readings_wanted`), which the member's gate checks but its expiry check never sees, makes each wanted reading again from the member's own meter rows, with the readings of the real-time calls it accepted, signs them afresh and flushes at once, under the chase's asked scope, so a chase is answered even with the same readings.

Receivers take each reading of a batch as if it came alone (`of_batch` over `_one_of_batch`): a reading that can't be read or raises costs only itself; the community market refuses a batch inside a batch, and the stand-in buyer reads one as another batch. The node host sends a batch under its id with `:<receiver>` appended, and a reading or batch addressed to one buyer goes, the same signed body, to every other buyer under `<id>:<buyer>`.

### 5. The real-time desk

During the day the community's desk (`gaps.GapDesk`) fills a buyer's call (`rt_call`) and the shortfalls members report (`rt_capacity`) from the members with room. A reported shortfall the sale's margin doesn't cover becomes a gap, a record of kind `gap` on the desk: no `rt_gap` message is sent or taken, and the desk logs each gap it takes up as `rt_gap`.

| Action | From, to | Message | Taken when |
|---|---|---|---|
| `rt_call` | buyer, community | `call`: `id`, `kind` (`short_notice`, `emergency`), `start`, `end`, `kw`, `price_usd_per_kwh`, `why` | it comes from a buyer under a new id. A pooled market also refuses a kW or price that isn't real and above 0, a `gap`, an end not after the start and an overlap with another call, answering `rt_confirm` 0 kW with `refused`. A call that arrives after its window is confirmed at 0 kW (`too_late`) and asks nobody |
| `rt_ask` | community, member | `ask`: `id`, `start`, `end`, `price_usd_per_kwh`, `kind` | the member's gate passes it |
| `rt_answer` | member, community | `answer`: `id`, `kw`, `below_min_price` | the desk asked that member under that id; its kW counts from 0 up to the member's nameplate where one is on file. A fixed plan, a price under the owner's `rt_min_price`, or a pool or quiet member that an alarm, a stop or a closed building holds answers 0 kW |
| `rt_dispatch` | community, member | `dispatch`: `id`, `steps` (kW by quarter hour), `price_usd_per_kwh`, `kind`, `start`, `end`, and `event_id` when it covers a booked sale; or `steps` below 0 with `release: true` | the member's gate passes it. The member owes the kW on top of its booking: under the sale, or under a contract `<call id>:<member>` whose readings carry the call's id |
| `rt_confirm` | community, buyer | `confirm` (`id`, `kw`, `short_kw`, `homes`, or `refused` or `too_late`), `dispatched` (`id`, `alloc`), or `warning` (`id`, `short_kw`, `start`, `end`, `why`) | it names a call this buyer made; a call pays only the members `dispatched` names |
| `rt_capacity` | member, community | `short` (kW by quarter hour), `abnormal`, `drift` | a report made (`sentWall`) before the one taken last is ignored. A pooled market takes it only from a member, counts each kW up to what the member owes there, and reads a reason off `KNOWN_REASONS` as `not given` |
| `rt_end` | buyer, community | `end`: `id`, `at` | a buyer may send it to end its call early. It comes from the call's own buyer, once; each allocation from `at` on is released. The stand-in buyers never send it |

The desk allocates once every member asked has answered, once the answers in hand cover the call with its 10 % margin, or the gap (live, without `clock_waits`), or once 5 dataset minutes have passed (live, also `rt_answer_wait_s`, 25 s, plus the inbox's lag up to 90 s): biggest answers first, over a call's quarter hours evenly and over a gap's as its shortfall runs. Under `report_rule` = `exception` a call asks the members a wave at a time (32, then twice as many while it is short, biggest first), and a gap asks the members with the most room on file until that room adds up to 1.5 times the gap. A gap still short is asked again at 1.25 and then 1.5 times its first price (`PRICE_LADDER`), and then the buyers are warned.

The desk's messages are sealed under the community's play, keyed with the call's id and a digest of what they say; an ask and a dispatch carry the round and the wave instead, so a later round or wave can reach a member again. A buyer's call is sealed under its play with its id, `call-<date>-<HHMM>-<kind>-<6 hex>`. A member's answer goes under the ask's asked id, and its `rt_capacity`, transaction `cap-<name>`, is sealed with the dataset time and a digest of what it says. A call's readings are chased as a sale's are (`status` with `readings_wanted` naming the call) and checked as section 19 says. What is left of a call's bill once the members the desk dispatched are paid is the call's `fee_usd` (`gaps_settle.py`).

### 6. Acknowledgements

A handler returns text, and its type sets the acknowledgement: `ack_of(note, limit=200, field="note")` gives `(status, {field: note[:limit]})`.

| Handler answer | Status | Means |
|---|---|---|
| plain `str` | `processed` | the work is done, or was done before: a repeat of a settlement, a payment or an answer stays `processed` |
| `Refused(text)` | `rejected` | not acted on: a bad signature, an unknown sender, past its time, unreadable, nothing to do with it |
| `Partly(text, n)` | `processed`, with `"refused": n` | a batch in which n readings were refused and the rest counted |

`of_batch(parts)` joins the parts' answers (300 characters at most) into `Refused` when every part was refused, `Partly` when some were, plain text when none were. A handler that raises is acknowledged `rejected`, with the error in its note, by the node host, the community service and the stand-in buyer, and as `that message can't be read` by the aggregator and a single site; the community service also rejects a kind it doesn't know (`{"reason": "unknown_kind"}`). Nothing sends `retryable`. A message whose acknowledgement fails stays leased, and the bus hands it out again.

### 7. The bus's HTTP contract, version 0.2.0

The bus stores and compares bodies but checks no signature: every receiver does that itself. `demo/runner/bus.py` is the local bus that the runner and the tests use (`make_bus(runs)`, app version `0.2.0`); its run comes from the runner's `bus.json` through `runs_from({"run_id", "tokens", "controllers"})`. It holds every run's sessions, messages and record in memory, so a restart of the bus loses them all. Participants reach a bus at the setting `town_url`, in the run `town_run_id`.

| Route | Request | Answer |
|---|---|---|
| `POST /runs/{run}/join` | `{"name", "token"}` or `{"name", "grant", "grant_signature", "session_proof"}` | `{"session"}`; 403 for an unknown name or token, or a grant that doesn't hold |
| `POST /runs/{run}/messages` | `{"message_id", "to", "kind", "body"}` | 200 `{"message_id", "accepted": true, "replay": false}`; 200 with `"replay": true` for the same id from the same sender to the same receiver with the same kind and canonical body; 409 `{"accepted": false, "why": "this id holds another message"}` for anything else under a taken id; 400 without `message_id` or `to` |
| `GET /runs/{run}/inbox/notify?wait=` | | `{"hint": true}` while the caller's inbox holds a message to hand out |
| `POST /runs/{run}/inbox/claim` | | the oldest message to hand out, `{"message_id", "kind", "body", "fence", "from", "to"}`, or 204 |
| `POST /runs/{run}/inbox/ack` | `{"message_id", "fence", "status", "note"}` | `{"ok": true}`; 409 `{"stale_fence": true}` |
| `GET /runs/{run}/record?after=n` | | `{"events": [...], "next": n}`: every accepted message and every ack, in order |
| `GET /health` | | `{"ok": true, "runs": [...]}` |

Every route but join, record and health takes the session in the `X-Town-Session` header and answers 401 `no such session` without a live one. An unknown run is 404.

**Join.** A join ends every earlier session of the name and opens a new one (32 hex). With a token, the name must have one in the run and it must match (`secrets.compare_digest`). With a grant (`grants.py`), each name has a controller key that stays with the runner (`Controllers(folder)`: one `<name>.controller.key`, mode 600), whose public half the bus pins (`controllers` in `bus.json`). For one run the controller signs a grant that names a fresh session key:

```text
{"agent_id": "did:town:<24 hex>", "run_id": "<run>", "session_public": "<64 hex>",
 "permissions": ["ack", "claim", "join", "send"], "issued_at": <t>, "expires_at": <t + 3600>}
```

`agent_id` is a hash of the controller's public key; the times are wall-clock seconds, and a grant lasts 3600 s (`grants.TTL_S`). The participant gets the grant, its signature and only the session's private half (`secrets/town_grants.json`, mode 600), and proves it holds that half by signing `{"purpose": "join", "run_id", "name"}` in canonical JSON (`transport.join_proof`). `grants.verify` refuses, with the reason, unless in this order: the grant is an object naming this run; `permissions` is a list of names; `issued_at` and `expires_at` are finite numbers, not booleans; the grant has not expired; it is signed by the name's pinned controller; the proof verifies against `session_public`. It compares neither `issued_at` with the time nor the listed permissions with what the session does.

**Send.** One id holds one message. The same message again (sender, receiver, kind and body) is a replay; anything else under a taken id is refused and goes nowhere, and the id keeps its first message. An accepted message is queued in the receiver's inbox, for any `to`, a name the run knows or not, and recorded as `accepted`.

**Notify.** A hint is a wake-up call, never the message. The local bus answers from the inbox's state and ignores `wait`; clients always send `wait=0`, so no request is held open.

**Claim, lease, fence.** A claim hands out the oldest message that is queued or whose lease has run out, leases it for `lease_s` (30 s, `LEASE_S`), and gives it a new fence (16 hex) at each hand-out. A lease that runs out hands the message out again, with a new fence. The local bus's claim answer carries no `attempt` or `duplicate`.

**Ack.** An ack must name a message addressed to the caller, in state `leased`, with the fence of its last hand-out. The lease's end is not checked: an ack with the last fence still finishes a message whose lease ran out, as long as no claim has handed it out again. The message is then done, leaves the inbox, and the ack is recorded with its status and note. Anything else is 409 `stale_fence`, so an old hand-out can't finish a message handed out again.

### 8. The client: sessions, retries and the sent journal

`transport.TownSession(base_url, run_id, name, token, http)` is one participant name's session; a host shares one HTTP client among its members' sessions.

- **Join.** `_join` uses the grant held for the name in `secrets/town_grants.json` (`grant`, `grant_signature`, `session_private`), and otherwise the token. The community, the aggregator, each single site and each stand-in buyer call `join_until_up`: it joins in the background and, after any failure, a refusal (403) included, tries again every 15 s for as long as the process runs, then starts the inbox; the service's own routes stay up meanwhile. The node host joins its members once each, one after another (`join_all`); a member that didn't join then joins at its first call.
- **Every call** joins first when there is no session. A dropped connection is tried once more after 0.3 s. A 401 makes the session join again, only if no other thread has joined since it read the old session, and repeat the call once. A 502, 503 or 504 is repeated once after 0.5 s. The repeats after a dropped connection and after a 5xx count in `retried`; the one after a 401 doesn't. Each call's time goes into `timing()` (p50 and p95 by kind).
- **One process per name.** Three rejoins after a 401 within 120 s (`CONFLICT_REJOINS`, `CONFLICT_WINDOW`) mean another process holds the name: the session pauses 60 s (`CONFLICT_PAUSE`) and raises `TownIdentityConflict` instead of taking the name back again; the inbox poller waits the pause out.
- **`send(to, kind, body, message_id)`** posts the body that `Sent.body_for` gives. A 409 returns `{"message_id", "duplicate": true}` and counts in `dropped`; a replay counts in `replays`; any other failure raises. `TownWatch` tells `/health` whether the bus answered lately and how many sends failed in the last 60 s.

**The sent journal.** `transport.Sent` holds a session's last 512 bodies by message id, in memory only, so it lasts as long as the process. `body_for(id, to, kind, body)` returns:

1. for a new id, this body, which it keeps;
2. for the same id, receiver and kind with the same meaning, while the first body is within its time to live, the first body, so the bus answers replay;
3. for the same meaning once the first body has expired, this body, which it keeps: the bus takes it if the first never arrived and refuses it if it did, and then the first is what counts;
4. for a different meaning, this body as it is, not kept, to be refused.

`meaning(body)` is the body without `sig` at any depth and without `timestamp`, `sentWall` and `messageId` in any `context`, so a body made again with a new time and signature means the same. After a restart a body made again goes as it is: the bus takes it if the first never arrived and refuses it (409) if it did.

**Retries** of a failed send, always under the same message id:

| Sender | Retry |
|---|---|
| Node host (`agents/host.py`) | a failed send again after 5, 15, 45, 120 and 300 s (`RETRY_S`), except a single reading to the receiver it was made for, which a `MemberNode` or `PoolNode` tick sends again until both of its sends went through. Its copies to other buyers and a quiet member's batch, which holds no `performance`, take these retries |
| Community market | a broadcast in rounds of three tries, with a 2 s pause after each failed try; what is left goes again in a new round 15 s after the first round ends and 45 s after the second (`BROADCAST_AGAIN_S`), then `v2_send_gave_up` is logged. Report rows go upward oldest first, and after a failure the next lot waits `report_up_retry_s` (30 s); its answer to the aggregator goes once |
| Stand-in buyer | a reply or a call the bus didn't take waits in `unsent` and goes again at each tick, oldest first |
| Aggregator stand-in | a request goes at its `made_at` dataset time, and while `aggregator_waits_for_start` is true (the default) only once its clock has been set (`POST /demo/clock`); one the bus didn't take goes again at the next tick |
| Single site | its answer goes on its own thread; one the bus didn't take goes again when the request comes again, or at a tick at least 5 s (`ANSWER_RETRY_S`) after the last try, until the bus has it. Report rows go oldest first, and from the first that fails they go again at the next tick |
| Inbox | a claim tried once more at once on a dropped connection (`inbox._once_more`) |

### 9. Inboxes

`inbox.InboxPoller(town, handle, every=1.0, idle_every=4.0, idle_after=60.0, sweep=30.0, lease=30.0, claimers=1)` watches one inbox with short checks:

- a check every `every` s while mail flows, every `idle_every` s once nothing has come for `idle_after` s;
- on a hint it claims until the inbox is empty. A message the claim answer marks as a first hand-out (`attempt` 1 or absent, no `duplicate`) left a hint behind, so a pass with n first hand-outs leaves n − 1 hints, which are popped without another claim pass, while new mail still gets a pass every `every` s. The local bus's claim answer carries neither field, so there every hand-out counts as a first one, a hand-out after a lease included;
- a hint with nothing to claim, or a claim that failed on the way, gets one more pass after a lease (`lease × 1.1 + 0.2` s): a claim whose answer was lost comes back then;
- a check that failed, or had to be tried again, gets a pass at once;
- a pass every `sweep` s in any case;
- with `claimers` > 1, a pass that finds a message brings in that many claimers in parallel; an empty inbox costs one claim.

`handle` processes and acknowledges a message; one it raises on is not acknowledged and comes back after its lease. The services pass `town_poll_seconds` (1.0) and `town_poll_idle_seconds` (3.0); the stand-in buyer claims with `utility_inbox_workers` (12), the community service with `catchup_workers` (16) until its inbox has been empty once, then `inbox_workers` (4), and the aggregator and a single site with one claimer. `LagMeter` tells how far behind an inbox is: the median of claim time less `sentWall` over the last 20 s, over the messages the claim answer marks as first hand-outs (on the local bus, all of them), and 0 with fewer than 3.

The node host polls its members' inboxes itself (`NodeHost.poll_loop`): `host_poll_workers` threads share the members; each member is checked every `host_poll_seconds` (5) for a minute after its last mail and every `host_poll_idle_seconds` (15) otherwise, with a claim pass every `host_sweep_seconds` (60) whatever the hint says. A member whose agent thinks takes its mail on its own thread.

### 10. Idempotency and restarts

| Layer | Why a repeat changes nothing |
|---|---|
| Bus | one id holds one message, and the same message again is a replay |
| Sender | a retry sends its first body (`Sent`), and an id is a pure function of what the message is (section 3) |
| Node host | it keeps, in memory, the last 512 finished ids per member (`KEEP_SEEN`) with the status each came to. A copy of a finished message is acknowledged again with that status and the note `a repeat: already taken`, and is not acted on. A copy of one still in work is left alone, and the bus hands it out again after its lease. Neither list is saved: after a restart a message handed out again runs again, and only the member's own rules below keep that harmless |
| Member | a commitment it answered gets the same answer, and an accepted one is never turned into a decline; a call for offers asked again sends the same offer; a payment notice counts once per `(event_id, top_up)` |
| Agent | each market step (1 to 6) is recorded once per sale (`market_seen`) |
| Node context | a device call that went (`done` or `adjusted`) is taken once per step, time, tool, arguments, start and end (`Steps.once`, on the node's log). A repeat in the same process comes back blocked (`acted`, in memory); after a restart the first answer comes back. A call a crash cut off answers `failed` and is not sent again |
| Community market | an answer to a commitment is final; the first reading of a half hour stands; a settlement whose `top_up` is not above the one held is ignored |
| Stand-in buyer | the first reading of a half hour sets its usage, battery and pre-event load, and a repeat may only say the same (within 0.004 kW); a later reading's `committed_kw` replaces the one held, which counts only inside the coordinator's range (section 19); a contract step repeated gets the same reply |
| Aggregator stand-in | an answer is noted once, a report row once per quarter hour, and a different row for a quarter hour already kept is refused |
| Single site | a request asked again is not answered anew: its first answer goes again if the bus never took it |
| Settlement | settling the same readings twice gives the same money and leaves its inputs as they were |

**What a restart keeps.** On disk: each participant's keys; the community's pins (`state/home_pins.json`, written whole; a file that can't be read is set aside as `home_pins.json.old`, and each sender is pinned again at its next message); each node's book and floor (`state/person/<node>.json` and `.floor`, section 18); and a thinking node's log, `state/decisions/<node>.jsonl`, from which its context brings back its alarm stop, the wishes in force, the groups a person closed, a person's signed words and its device calls' answers. In memory only, among others: the local bus, `Sent`, the node host's `seen` and `taking`, a context's `acted`, and every sender's play.

## Part 2. Safety

### 11. Who decides what

Code decides every amount. The model reads what a person writes and words the report; it never sets a kW, a limit, a plan or a payment.

| Decision | Made by |
|---|---|
| Forecast, safe offer, how much of it goes out, the answer to a commitment | code (`home_forecast.py`, `home_offer.py`, `offer_rule.py`). At a call for offers the agent first reads a note still waiting (`read_note`), which may ask the model; the model sets no amount there |
| The sale's device plan at its opening and at every exception | code: `NodeAgent.decide` is `AgentPlan.by_step`, whose plan runs through `carry_out` and is recorded as `plans are decided by code` (`modes.BY_CODE`) |
| A person's note | the model reads it into wishes from a fixed list; code works out each wish's end and what it blocks (section 12) |
| The report after a sale | code writes the facts and the numbers; the model words the facts (section 13) |
| Every device write | the guard, through the seal (sections 14 to 17) |
| Readings, baselines, pay | code (sections 19 and 20) |

A member's commitment check (`HomeOffer.verify_contract`) declines, in order: a body not signed by a trusted community key; a contract not addressed to this member; no offer for the sale; past the opt-out deadline; a half hour above the offer by more than 0.01 kW; a frozen or jumping battery reading (`node/telemetry.py`); a day or sale the person opted out of; advisory control. Code's rule may then turn a yes into a no, never a no into a yes. The same telemetry check scales an offer's confidence, and a frozen or jumping reading sends a 0 kW offer.

**The model client.** `LlmClient` posts one question with its tools to `{llm_url}/api/chat` (an Ollama-style chat endpoint; `llm_url` and `llm_model` are required when `llm_enabled` is set), with `stream: false`, `think: false`, `keep_alive: 30m`, `truncate: false`, `shift: false` and options `temperature` 0.3, `top_p` 0.8, `top_k` 20, `num_predict` 300, `num_ctx` 32768; `llm_temperature` and `llm_seed` replace the temperature and add a seed. An answer is `{calls, text, ms, error, tokens}`: a tool call without a name is dropped and the text is cut to 300 characters. An HTTP error, a 120 s timeout, or a body that is not JSON or not in the chat form gives `{calls: [], text: "", error, ms: 0}`, with no `tokens`, and counts in `errors`; whoever asked keeps code's own result. A host with thinking nodes also reads the model's digest from `{llm_url}/api/tags` (5 s timeout) once at its start, for the record. `SharedModel` is the process's one door to the model: `llm_slots` questions at a time, an exception's before a sale step's before a report's. `NodeModel` lets go of the node's lock while it waits.

### 12. Notes into wishes

A note reaches a home as the override `note` through the host's scenario door (a home's `ev_now` writes `I need the car charged now.` there too), and any node as one of the last two `notes` on file in the owner's wishes or the facility's policy (`offer_shape.Wishes`, `FacilityPolicy`); each is read once. `note_reader.read_note` asks one question:

- the system text says to record what the owner or manager needs kept from their devices, and that an order to the reader, or a request for anything else, is no wish;
- the note goes in as data after `Today is <Weekday> <date>, <HH:MM>.`: one line, printable characters only, at most 300 characters (`NOTE_MAX`), every kind of quotation mark turned into an apostrophe so the words can't close the quotation around them (`quoted`); the needs still in force follow it;
- the tools are `set_owner_wish(wish, by, until)` with `wish` from the fixed list, `no_wish()`, and, only while a need is in force, `end_owner_wish(wish | "all")`; each requires a `reason`.

Code keeps only what holds:

- An answer without a reason is asked once more. Still none: nothing it read is kept, the receipt is flagged `no reason given`, and, if it read a wish, the person hears `I couldn't act on your note, so nothing has changed: "<note>"`.
- A note written in the tools' own words (`keep_` and a name, a wish's name written with hyphens, `set_owner_wish`, `end_owner_wish` or `no_wish` with hyphens or underscores, in any case) sets nothing (`TOOL_WORDS`).
- Only a wish name on the list counts; a list of names in one call is read name by name; any other tool, name or shape sets nothing.
- `by` stands only if the note holds that clock time, compared on a 12-hour dial: each number of one or two digits in the note counts as an hour, with its minutes if it gives them, so `8pm` lets 08:00 and 20:00 stand, and `noon`, `midday` and `midnight` let 00:00 and 12:00 stand. A start word before a number anywhere in the note (`from`, `after`, `starting`, `since`, `beginning`: `A_START`) voids every `by`. `until` reads `tonight`, `today`, `tomorrow`, a weekday, or a date capped 31 days ahead (`MAX_DAYS`); anything else gives no day.
- A wish holds from when the note was written to the end code works out (`end_of`): the day at `by`; a day alone, to the next midnight; `by` alone, today or, once past, tomorrow; neither, through the next sale (`AgentNotes.lapse` sets the end of the first sale still owed, or ends the wish after the day following its note when no sale comes). A wish whose end is already past is not held.
- `end_owner_wish` takes back a need in force, by its name or all of them.
- A person's `I need the car charged now.` (`CAR_NOW`) adds `keep_car_ready` whatever else the model reads, once the reader has answered; with no answer the note waits for the next step like any other. The car charges first through the `ev_now` override all the same.

The careful step (`read_note_carefully`, chosen by `MURMUR_CAREFUL_NOTES`, else `careful_notes` in `agent.json`) adds examples of how people write (`HELP`). A reading that can't stand, no answer or no reason twice, keeps every device until tonight is over (`keep_everything`, why `no reading`), tells the person `I couldn't read your note just now, so I've left everything as it is until tonight is over.`, and reads the note again at the next step; a note that gave no reason twice waits until the next sale opens. An end already past when the note was written moves to the next time that clock comes round.

**What a wish blocks** (`note_reader.BLOCKS`, `BuildingGuard.kept`):

| Wish | Tools the guard refuses |
|---|---|
| `keep_battery_full` | `set_battery`, except `hold` and `charge` |
| `keep_car_ready` | `limit_ev_charging`, `discharge_car`; the car charges first (`ev_now`) |
| `keep_house_as_is` | `set_thermostat`, `set_room_ac`; at a building also `set_zone_cooling`, `set_zone_standby`, `limit_air_handler`, `set_plant_demand_limit`, `stop_plant_early` |
| `keep_hot_water` | `set_water_heater` |
| `keep_machines_on` | `delay_appliance`, `set_pool_pump`, `switch_plugs` |
| `keep_lights_on` | `dim_lights` |

A wish in force also drops the running calls on those tools and closes their levers, and the next offer leaves out what it keeps (`grounds.keep_out`). A note that takes kW out of a sale already committed is measured against the amount without it, and the person hears the cost: `Got it: keeping the battery full, as you asked, so I'm giving 1.0 kW tomorrow night instead of 3.5.` A later note can take a wish back (`end_owner_wish`): the device goes back to the sale, the person hears `The owner took back a need, so what it kept out can be used again.`, and the next offer can grow again. No note touches a limit a person signed: those change only through the signed channel (section 18).

### 13. Reports

At a sale's end (step 9) `report.facts` lists what the node knows, each fact labelled `records`, `measured` or `human`. The model words them in two sentences through the tool `file_report`, or in its plain text; with neither, the first two facts are the report. The summary, the facts and what the person was told stay on the node's log. Upward go numbers only (`amount.REPORT`): `sale`, `ts`, `owed_kw`, `sold_kwh`, `delivered_kwh`, `short_kwh`, from the node's meter against its own day without the sale. When the meter shows more than 2% less than was sold, the person hears it on their own channel, ending `Only what the meter shows is paid.`

### 14. One device call

`ContextServer.act` hands a call to `calls.run_call`, which ends in `Gate.run`. The checks run in this order; the first refusal answers `blocked` with its reason, and nothing reaches a driver.

1. The node's step acts: `6 prepare`, `7 watch` or `8 exception`.
2. The tool is on the node's shelf.
3. `clean_args`: arguments are named values the tool's card lists; a number, or text that reads as one (kept as a float), is finite and inside its unit's range (kW 0 to 1e5, kWh 0 to 1e6, A 0 to 1000, percent 0 to 100, °C −10 to 10, any other unit −1e6 to 1e6); an enum takes one of its values; a `target` is plain text of at most 64 characters; `start` and `end` are code's.
4. The policy allows it (below).
5. The guard passes it (sections 15 and 16).
6. The seal and the driver deliver it (section 17).

**Policy** (`policy.default_rules`, kept as data). An unknown role, an unknown verb or an empty group is refused before any rule is read. `never` rules come first, then a person's closed groups, then `allow`; anything else is denied, and a rule of the wrong shape matches nothing.

| Rule | Who | Groups | Verbs |
|---|---|---|---|
| never | anyone | `life_safety`, `guard` | all |
| never | community | every device group | all: it may request and move a gap, and commands no device |
| never | agent | all | `set_limit`, `need_now`, `close_group`, `open_group`, `clear_alarm` |
| allow, signed | owner, at a home | `site` and every device group | `read`, `set_limit`, `need_now`, `close_group`, `open_group`, `clear_alarm` |
| allow, signed | facility manager, at a building | `site` and every device group | the same |
| allow, signed | owner, at a building | `site` and every device group | `read` |
| allow | agent | `site`, `market`, every device group | `read` |
| allow | agent | every device group | `call` |
| allow | agent | `market` | `trade` |
| allow, signed | community | `market` | `request`, `move_gap` |

A group a person closed (`close_group`, `need_now`) refuses the agent's calls until the person opens it. The device groups come from each tool's card: `energy_storage`, `ev_charging`, `hvac_zones`, `water_heating`, `appliances`, `pools_and_water_features`, `central_plant`, `lighting_and_shading`, `plug_loads`.

### 15. The home guard

`guard.Guard.check(call, facts)`, plain code and the same for every home, in this order:

1. An alarm in the facts: `An alarm is on, so nothing is sent and every agent limit releases.`
2. A person's stop: `A person took this node out of the sale, so nothing is sent.`
3. A tool off the shelf: `This node has no <tool>.`
4. A target with no device for the tool: `<target> can't take this call now.`, with the tool's own target, if it has one, as `try_instead`.
5. A tool a wish blocks, in the wish's words, such as `The owner needs the battery kept full.`
6. A tool or target off the step's list (`menu`): `<tool> on <target> isn't on this step's list, so nothing was sent.`
7. The tool's own rules:

| Tool | Refused, or narrowed, when |
|---|---|
| `set_battery` | the action is not charge, discharge or hold; the battery shut off under 10 min ago; kW is not a number above 0 (try hold); a charge runs into the sale window (try hold); there is no charge limit, or the charge passes it (narrowed); a discharge finds nothing above the owner's reserve, or asks more than keeps it (narrowed) |
| `limit_ev_charging` | the car isn't charging; amps are not a number of 0 or more (anything between 0 and 6 A becomes 6 A, and the charger's maximum caps it); at any amps, the full-power charging the call puts off (its hours, at least a quarter hour, × the share of the charging power it holds back) passes the car's slack (`wait_h`), the time it can wait and still be ready |
| `discharge_car` | the car is charging (try pausing the charger) or not idle; kW, or a `max_kwh` given, is not above 0; the car has nothing to give and still be ready; it asks more than that (narrowed) |
| `set_thermostat`, `set_room_ac` | `less_comfort_c` is not a number; the unit isn't running; the offset is 0 or below (a pre-move is the controller's); it passes the home's limit (narrowed) |
| `set_water_heater` | no mixing valve is on record; a `load_up` whose call ends after the sale's start (try hold), or with the tank at normal; an action other than hold or `load_up`; hold with hot water low |
| `delay_appliance` | the machine isn't waiting; the call's end plus its cycle passes the done-by time. A `finish_by` that isn't `HH:MM` takes the done-by time, a later one is held to it, and one before the hold's end plus the cycle is raised to that (a time before 06:00 belongs to the same evening) |
| `set_pool_pump` | at 40 °F or below (freeze protection); filter hours short; not running; speed not a number, or at or above the running speed; below the pump's floor (raised to it) |

8. One writer per target: a call that overlaps a running one is refused, `<target> already runs a call until HH:MM.`; one that passes holds the target until its end and is confirmed at its start (`confirm_by`).

`guard.num` takes an integer, a float or text that reads as a number (`"5"` is 5.0); a boolean, NaN, infinity or other text is no number. An answer is `{status, target, applied, expected_kw, confirm_by, why, try_instead}`, with status `done`, `adjusted` (narrowed, with the reason), `blocked`, or, from the driver, `failed`.

### 16. The building guard

`guard_building.BuildingGuard.check` applies the same order to a building's tools, with more checks around it:

1. an alarm; 2. a person's stop; 3. a tool off the shelf;
4. a target with no device: the alternative the building's map names (`instead`) as `try_instead`; else a target whose name holds a word of the map's `never` list (stairs, exits, network rooms, the fire command room and the like) is refused as never touched; else the tool's own target is offered;
5. a `start` or `end` that is not a local time, `HH:MM` or with its date;
6. a write without a start and an end, with the sale's times as `try_instead`: every write ends by itself;
7. an end not after its start, or a write longer than a day (1440 min);
8. a tool a manager's wish blocks; `keep_house_as_is` blocks every climate tool;
9. a call off the step's list, except a writer giving back its own call (`set_zone_standby` mode `off`, `switch_plugs` state `auto`);
10. the tool's own rules; a reading the rule needs that is missing refuses the call: `A reading this call needs is missing (...), so nothing was sent.`;
11. a writer giving back its own call ends it, with no clash check;
12. one writer per point: a target's points (a plant's cap and its stop share one) take one call at a time, and a later call is offered the time after the earlier one ends. A passed call is confirmed 5 to 35 min after its start by tool (`CONFIRM_MIN`; lights off after 5), and `confirm` marks it `failed` when the device's reading shows it did not do what was sent.

| Tool | Refused, or narrowed, when |
|---|---|
| any zone tool | a room is in an exam; it is a time to avoid; a smoke role is not ruled out; the unit also cools a closet; an occupant override runs; dew point past 15 °C or RH past 65% |
| `set_zone_cooling` | no cooling runs; the offset is not a number, or 0; a pre-cool (below 0) runs into the sale, goes deeper than the zone's `precool_c` (narrowed), takes the setpoint under 13 °C, or closes the 2.8 °C gap to heating; the zone's limit is 0; above +1.5 °C in an open or booked zone (try +1.5 from 30 min before the sale); above +1.5 °C past 60 min before the next booking; above +3 °C (narrowed); above the zone's limit (narrowed); an occupied zone past its top temperature (narrowed); a setpoint above 29 °C |
| `set_zone_standby` | mode not on or off (off ends this node's own standby); a booking or event; a mall zone while open; an outdoor air unit serving an open zone; a room without a working occupant sensor; standby not allowed there (try +3 °C); past 60 min before the next booking; boxes that store each write: a window shorter than the sale, or the day's writes used up |
| `limit_air_handler` | a dedicated outdoor air unit; no outdoor airflow reading; a failed CO2 sensor; hood make-up air; speed not a number; under 50% (try 50%); at or above the running speed, as a cap never raises a fan; its zones not eased first; below the unit's floor (narrowed) |
| `set_plant_demand_limit` | chillers off; a computer room on the plant; a lab share without a live lab reading; zones not set to coast; limit not a number; under a person's lowered comfort limit (narrowed); at or above the running percent; under the labs' floor (running percent × lab share × 1.1) or the lowest chiller floor; each chiller held at its own floor (adjusted) |
| `stop_plant_early` | not a whole plant; labs or another building share the water; chillers off; a hot evening or a lowered comfort limit (try a cap); no signed list that nothing critical hangs on the loop; no pre-cool today; the day's one stop used; an end before the plant's normal off time, which would be a second start |
| `dim_lights` | an exam; a time to avoid; a utility event; a person's override; an area that allows no load shed; lights off; a cut not from 1 to 100; a limit lowered to 0; on an exit route, no measured light to spare (1 fc or less), else at most 100 × (1 − 1/fc) %; off (100) without every area empty, on an exit route, or under a lowered limit; above 50% or the building's own limit (narrowed) |
| `switch_plugs` | `on` (try `auto`); a state other than off or auto; `auto` with nothing of this node's to give back; a second off after a hand-back in the window; an occupant override; a load that can't be switched; a zone that isn't free (empty and unbooked; unknown counts as occupied) |
| `set_battery` | the action is not charge, discharge or hold; tripped in the last 10 min; a utility command, a running generator or another program; kW not above 0; above the planning rating; a charge into the sale or past a window's charge limit; a discharge past the energy above the reserve, counting what running calls will still take; energy an award needs; export past a discharge limit; import at or under the trip point (narrowed to stay above it) |
| `limit_ev_charging` | ports with no control path; amps other than 0 or 6 to 80; no session drawing power; at or above every car's draw; a car that would leave short of its charge (try 6 A where that serves) |

### 17. The seal and the drivers

`drivers.Gate(node, guard, driver)` is the only road to a device: guard, then seal, then driver. Its only public methods are `run` and `release_all`.

- The gate draws a private 32-byte key when it is made, and its driver attaches to it for good; a second gate can't attach.
- `run(call, facts)` copies the guard's memory and asks the guard. On `done` or `adjusted` it makes a `Ticket`: the `Command` (node, tool, kind, target, applied values, start, end), the call, the guard's answer, a fresh 8-byte nonce, and the seal, HMAC-SHA256 under the gate's key over the nonce and the sorted, compact JSON of `[command, call, answer]`.
- `Driver.send(ticket)` refuses anything that is not a `Ticket`, whose seal does not verify under its own gate's key, or whose nonce was used before: `Nothing was sent: this command has no guard's seal.` A ticket is good once; a ticket from another gate, or with a changed nonce, seal or command, is refused.
- A guard that raises has said no: `The guard couldn't check this (<exception class>), so nothing was sent.` A driver that raises answers `failed`, `The device didn't take it: <exception class>.`, as a simulated write that raises does; neither has delivered. In both cases, and when a driver refuses, the guard's memory goes back to the copy, so the point is free again.
- Five command kinds (`KIND`): `setpoint` (thermostat, room AC, zone cooling), `schedule` (water heater, appliance, plant early stop), `cap_power` (car charging, pool pump, air handler, plant demand limit), `dim_switch` (lights, plugs, zone standby), `charge_discharge` (battery, car to home). A tool with no kind is refused.
- For the record only, the gate traces which lines of the guard's four files ran and keeps them with the command, the driver's reply and the seal cut to 16 characters; the trace changes nothing, and a fault in it never reaches the answer.
- `release_all()` ends every agent limit: the driver releases its devices and the guard forgets every point, even when the release fails.

Drivers come from `drivers.make(side, mode, group_of)`, with the mode from `MURMUR_DRIVERS` (default `simulated`):

| Driver | Behaviour |
|---|---|
| `SimulatedDriver` | acts on the dataset's replay through the node's own write, release, read and limit functions; a write that raises answers `failed` |
| `Router` (mode `real`) | one real driver per device group: at a home `energy_storage`, `water_heating`, `appliances` and `pools_and_water_features` on Home Assistant, `ev_charging` on OCPP, `hvac_zones` on Matter; at a building `energy_storage` on Modbus, `ev_charging` on OCPP, and the plant, zones, lights and plugs on BACnet. A write or a limit for a group with no route is refused (`No driver is set up for <target or group>.`), a read always is (`No real driver is connected, so <target> can't be read.`), and a release goes to every route |
| each real driver | refuses every write and limit (`<protocol> driver isn't connected, so nothing was sent to <target or group>.`), answers a release with nothing sent, and imports no network code. `BacnetDriver`'s docstring asks writes to use priority 9 to 14; no code sets a priority, since no write is sent |

Any other mode raises `ValueError`. On real drivers every device call comes back `blocked`, and the guard forgets it.

### 18. Alarms, a person's stop and limits

**An alarm.** A life-safety signal reaches a node as the override `alarm` carrying the signal's words (`{"override": {"home": "<node>", "kind": "alarm", "value": "smoke"}}` on the host's `/demo/scenario` door). It sets `alarm`, `alarm_hold` and `stop`. From then:

- the guard refuses every call (step 1), and the context's stop reads as the alarm whatever the signal does next;
- at the node's next agent step `ContextServer.alarm` releases every agent limit through `release_all`, once, records the alarm, and holds the controller; the agent's running calls are dropped;
- a pool or quiet member (`report_rule.PoolNode`, `QuietNode`) stops its plan, offers 0 kW, declines a commitment (`an_alarm_holds_this_node`), answers a call with 0 kW, and reports what it still owes as short (`rt_capacity`);
- the signal's end (value false or null) removes `alarm` and leaves `alarm_hold`: the hold survives a clear, a reset (`/demo/reset` has no signature, so it keeps the alarm) and a restart;
- only a person's signed `clear_alarm` ends it, and only once the signal is over (`The alarm is still on.` before).

The hold outlives the process. The host writes the node's book, `state/person/<node>.json` (`hold`, `signal`, the limits a person signed, each signer's last number), atomically and before the door answers; a disk that won't take it keeps the alarm in memory, says so on `/health`, and tries again at each tick. At start the book, once it exists, is the whole truth: a book that can't be read is moved aside (`.bad`), the node is held (`the node's alarm file can't be read`) until a person clears it, and the floor is set (below). A thinking node also restores the stop from its decision log.

**A person's stop.** The override `stop` takes the node out of the sale: the guard refuses every call (step 2), no plan is made, a pool or quiet member answers a call with 0 kW, and the member reports what it still owes as short. `clear`, or `stop` with value false or null, ends it, except while `alarm_hold` is set: then neither does.

**A person's signed word** (`policy.OwnerChannel`, through `POST /person/<node>` on the host, which answers 404 for a node it doesn't run). The message `{"role", "node", "seq", "verb", "group", "name", "value"}` is signed with the person's Ed25519 key on their own device (`policy.signed`). The channel answers `blocked` unless, in this order:

1. the signature verifies against the role's public key in `person_keys` (`agent.json`); with no keys on file nothing passes;
2. `node` is this node;
3. `seq` is an integer above the last one that key used on this node (`This message was already used.`);
4. the policy lets that role, as a signed person, use the verb on the group;
5. for `set_limit`, the limit is one a person may set and the value a finite number in its range:

| Group | Limit | Range |
|---|---|---|
| `hvac_zones` | `max_rise_c`, `max_rise_away_c` | 0 to 4 °C |
| `hvac_zones` | `precool_c` | 0 to 3 °C |
| `energy_storage` | `reserve_pct` | 0 to 100 |
| `lighting_and_shading` | `light_dim_max` | 0 to 0.5 |

Then the number is saved before the word does anything (a number that can't be saved stops the word: `Sign it again.`), a closed or opened group is set, and the change applies. On a node with no agent the channel (`host_people.code_channel`) applies only `set_limit` and `clear_alarm`; `close_group`, `open_group` and `need_now` answer blocked there. A signer's number only goes up; after a lost book no number at or below the moment of the loss, in milliseconds, is taken (`person.floor`), so no old word comes back. `python -m murmur.node.person token|key|trust|word` makes the control token, makes a person's key and prints its public half, adds a public key to `person_keys`, and sends a signed word; none of them prints a secret.

**The scenario door** (`POST /demo/scenario` on a host, `/b/<name>/demo/scenario` for one building) takes an override `{"home", "kind", "value", "source"}` for a node the host runs: at a home `ev_now`, `comfort`, `stop`, `depart_at`, `clear`, `note` or `alarm`; at a building `comfort`, `lights`, `stop`, `clear` or `alarm`. A switch (`ev_now`, `stop`, `clear`, `alarm`) takes true, false, null or plain text of at most 400 characters; `note` plain text, false or null; `depart_at` a `YYYY-MM-DD HH:MM` time; `comfort` an object of `max_rise_c`, `max_rise_away_c` and `precool_c` inside the policy's ranges; `lights` a finite number. Anything else answers 400, and a node without real-time control 409. A limit goes up only by a signed word: the door refuses (403) a `comfort` or `lights` that would raise a person's limit, and frees no alarm, by `clear`, a reset or the signal's end.

**The control token** (`protocol/doors.py`). The participants' services carry `doors.door()`: the node hosts, the community, the aggregator, each single site and each stand-in buyer. Once `secrets/control_token` exists, every request but GET, HEAD and OPTIONS needs it in the `X-Murmur-Token` header (compared in constant time), and a missing or wrong one answers 401; a token file that is empty or can't be read shuts every such request. Without the file nothing is asked, and `/health` says `token` or `open`. The local bus, the stand-in model and the state feed take no token. The token marks one of this system's own tools: it frees no alarm and raises no limit.

### 19. The meter checks a reading must pass

`meter_check.facts(name)` reads each member's enrolment from the dataset (`fleet_v2.json` and the buildings' files): the nameplate `rated_kw` (battery, car charger, half the cooling capacity, every enrolled device), `intake_kw` (the nameplate less a two-way car), `export_kw`, `battery_kw` (battery and two-way car) and `stored_kwh` (energy above the reserve, after losses). A name the data doesn't hold has none, and its readings are checked as numbers only.

`reading_problem` refuses, in order, a reading that:

1. is not an object (`it isn't a reading`);
2. names no integer slot (a boolean or text is none), or a slot the sale doesn't have;
3. has a `usage_kw` that is not a real number, a `committed_kw` or `battery_kw` given and not real, or a negative `committed_kw`;
4. with enrolment facts: sends out more than the meter's export limit; takes in more than its baseline (or, with none, its nameplate) plus what it can add; charges a battery faster than it takes (each with 0.02 kW of tolerance).

A real number is an `int` or `float`, not a boolean, and finite; text never is one.

| Door | Adds |
|---|---|
| Buyer (`buyer_refuses`) | the contract's slots and baseline; a repeat of a half hour that differs from the reading in by more than 0.004 kW in usage or battery (`it changes a reading already in`). A refused half hour with no reading in is marked so nobody waits for it, and a later true reading clears the mark |
| Community market (`market_refuses`) | a reading sent before this run started is ignored; it must name an event; it must be the sender's own (`it's another node's reading`); in a pooled market only a half hour the member owes counts (`it owes nothing in slot <n>`); a change to `usage_kw` or `battery_kw` of a reading in is refused |
| A real-time call's reading, at the buyer (`call_refuses`, `take_list`, `call_row`) | its start is a half hour from the call's first to 6 h past its end; once the desk's list is in, only a node it dispatched counts and readings already in from others are taken out; the dispatched kW is the desk's word; battery kW stop at the enrolled battery |
| Pre-event load (`pre_kw`) | a real number inside what the meter could take in; the first stands, a repeat half hour can't bring one, and a different one is counted and left out while the reading stands |

Each refused reading is counted, logged with its reason and answered `Refused`, so the bus records it `rejected`. A reading's `committed_kw` moves what a member owed only inside the coordinator's range for that half hour, from its contract's kW to that plus the gaps it was dispatched for (`against_owed`).

### 20. How settlement refuses impossible claims

**What counts** (`meter_check.counted`). A half hour without a baseline, marked abnormal (a building that closed), or never owed is left out; where the price book turns it on (`same_day_adjustment`), the baseline takes the pre-event load above its own baseline, never negative (`rules.adjusted`). `limit` then cuts each claim in place to what could be true, and the result says what was cut (`capped`):

- a home: battery output in each half hour to its enrolled battery; battery energy over the window to 1.1 × `stored_kwh` + 1 kWh; delivery in each half hour to its nameplate; where the contract holds the home's recent solar, delivery over the window to its stored energy + 1 kWh + its baseline load + 1.25 × the best solar of the days just gone; battery output in each half hour to what its meter delivered;
- a building: battery output in each half hour to its enrolled battery and over the window to 1.1 × `stored_kwh` + 1 kWh, as a home's, then in each half hour to what its meter delivered; its delivery counts at most 1.2 × its commitment in each half hour (`BUILDING_CAP_X`, `building_counted_kwh`).

**The money** (`rules.deg_settle`, `meter_kwh`, `share_out`). A battery's half hour counts its output, never below 0; a meter's other delivery is its baseline less its use less that battery output, netted over the event: when that part nets below 0 it is set to 0 in every half hour, and the battery's output is still paid. Under a building's cap the battery counts up to the cap and the rest up to what the cap leaves. Every kWh delivered is paid, with no cap at the offer and no penalty, except that in a half hour a real-time call covers the booking stops at the capacity sold and every class shrinks alike. Where the price book (`devices/price_book.json` in the dataset) states `coordinator_keeps`, each class's kWh is billed at the slot's price × the class's share `x` / (1 − `coordinator_keeps`); a book that states none bills every kWh at the slot's price. Buyer and seller flows sum to zero (`net_zero_ok`). A split never pays out more than its bills brought in (`within`), and rounding its shares to $0.0001 never pays out past the bill (`to_ten_thousandths`).

**The doors on money** (`market_checks`, `market_rules`):

| Check | Refuses |
|---|---|
| `offer_problem` | an offer with no slots; a slot without a whole id and a real kW of 0 or more; a slot the sale doesn't have; a part that isn't a real kW; the same slot twice; no real confidence or energy; held-back, evening or car figures it can't read or past the nameplate. A pooled market also refuses a non-member and, with nameplates on file, a member with none; the clearing counts each offer at most at its nameplate |
| `need_problem` | a buyer's order without readable ids; half hours not numbered from 0; a kW, price or penalty that isn't real (a price must be above 0); an unreadable name or currency; a deposit that isn't real |
| `settlement_problem` | not an object; no real sum for the sellers (real and at most 1e9 in size); a negative sum; an unreadable full price, components, caps, top-up round, currency or actuals; a sum for the sellers with no meter row that shows delivery; any number that isn't real; an unreadable list of what it lacks. A refused settlement is asked for again, and the order is on the alarm until one that can be read comes |
| `call_settlement_problem` | not this buyer's call; a sum that isn't real or is negative; a delivery past what the call could bring in (its kW × 0.25 h × its quarter hours, + 0.01 kWh); per-node kWh that isn't real, or that adds up to more than the call brought in |
| `baselines_problem`, `lacking_problem` | baselines that aren't `{node: {slot: {"BASELINE": real or null}}}`; a list of lacking half hours that isn't `{node: [int]}` |
| `clean_actuals`, `keep_lower`, `buyers_disagree` | a meter row with a value that isn't real costs that node alone; where two buyers hold different rows for one node, the row that pays it less counts; half hours where their copies differ by more than 0.004 kW are named in the result |

## Evidence

Each property above is pinned by tests. `pytest -q tests/test_protocol.py tests/test_transport.py tests/test_gaps.py tests/test_sites_aggregator.py tests/test_site_answers.py tests/test_aggregator_keys.py tests/test_guard_seal.py tests/test_guard_car.py tests/test_note_reader.py tests/test_settlement.py` runs them on the fixture dataset with no outside service: the bus runs in process, and the model server in `test_note_reader.py` binds port 0.

| File | Tests | What they pin down |
|---|---|---|
| `tests/test_protocol.py` | 13 | one key per file, mode 600; a signature breaks on any change and holds only against the pinned key; canonical form ignores key order; the envelope's context, and an envelope made again with its own id and time is the same byte for byte; integer keys signed as they arrive; ttl and expiry; local time arithmetic; `Refused` and `Partly` to bus statuses; sealed ids stable per key and unforgeable; asked ids scoped by the question; a batch named by its slots in any order |
| `tests/test_transport.py` | 9 | send, claim and ack; replay versus refusal, and the same id from another sender refused; a retry made again sends the first body, a changed one is refused; a lease that runs out hands the message out again and the old fence is stale; a replaced session joins again; a name taken a third time within two minutes pauses its session; a wrong or missing token or an unknown name is refused; a grant join proves the session key; the inbox poller hands each message over once with two claimers and leaves one its handler fails on unacknowledged |
| `tests/test_gaps.py` | 17 | a call filled from the biggest answers up to the call and its margin; a shortfall counted for what is owed and filled by the others, the margin's share moving no power, and up the price ladder when nobody can fill it; the quiet path's asking; a call's pay and its top-ups; a repeated call, answer or end changes nothing; an answer from a member not asked, a stale or a non-member's report, and an overlapping or late call refused; an answer past its time to live dropped and a fresh one held to the nameplate |
| `tests/test_sites_aggregator.py` | 18 | a site's limits and its store; the control door; a site takes a request only from its aggregator under its key; the aggregator keeps each quarter hour once, refuses a different second row, a stranger's, a forged or misaddressed message and an answer to nothing it asked, holds a site enrolled without a key to its first message's key, and flags rows; a row the bus didn't take goes up at the next tick, in order and once |
| `tests/test_site_answers.py` | 2 | a request row whose time can't be read gets a signed refusal; an answer the bus didn't take goes again under the same id, and once |
| `tests/test_aggregator_keys.py` | 2 | a forged first message pins nothing and the real sender is heard after it; once a key is pinned, a message signed with another is refused |
| `tests/test_guard_seal.py` | 22 | the home guard's order (alarm, stop, shelf, target, wishes, the step's list, each tool's rules, one writer per target); the building guard's never-touched list, times, shared points and missing readings; only `Gate.run` makes a ticket and a driver takes only a fresh ticket from its own gate; a guard or driver that breaks sends nothing and frees the point; the real drivers refuse every write; `release_all` ends every limit |
| `tests/test_guard_car.py` | 4 | a car's limit, a pause or a partial one, may put off only as much full-power charging as the car can wait for; amps under 6 rise to 6 and stop at the charger's maximum |
| `tests/test_note_reader.py` | 35 | a note into a wish from its writing to the end code works out; each need blocks its own part's tools; the request the client sends; `end_owner_wish`; no reason twice; unknown tools and values out of range; the tools' own words; malformed, late or failing model answers keep code's result; the careful step; what the person hears; a door note and the notes on file read once; a car-now note; a signer's number only goes up and starts above the floor after a lost file; `trust` |
| `tests/test_settlement.py` | 56 | baselines and their fall-backs; the same-day adjustment; delivery and each class's pay; a split never pays more than its bill; impossible readings refused with their reason; a repeat that changes a reading refused; a claim cut once to nameplate, battery and meter; what a node owes; a call's reading held to the desk's dispatch; settlements and baselines that can't be read refused; settling twice gives the same money |

`tests/test_runner.py` adds that every grant a run folder holds, for the community and the buyers, the homes, the buildings, the aggregator and each single site, verifies against the bus's pinned controller, and that the bus refuses a grant another controller signed.
