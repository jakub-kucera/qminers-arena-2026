# The calls behind the bots

AI agents wrote most of this repository's code and ran most of its experiments: Claude Code here, and Codex in a
second repository started from the organisers' bare starter (`codex_repo/`). Jakub decided, in his prompts, what they
worked on, which results to believe and what to upload. This page lists those calls. They were read back from the
sessions' logs after the event; the logs themselves are not published. Each call has its time (Prague) and the
prompt as typed ("…" marks a cut), followed by what came of it.

## The prepared repository and a clean start

The month of prep had been built on IMC Prosperity data, a different market, and it led the first hours the wrong
way. Jakub started a second agent on a clean slate beside it and made the two compete.

- **Sat 10:13 (Codex).** *"this is starter repo for a competition. do an initial research of it. I need to win. make
  no mistakes"*. This was the second session, in its own repository with only the organisers' starter.
- **10:46 and 10:57, the playground.** The prepared session's first bot to run lost 7,598, after a series of uploads
  that failed the sandbox's static analysis. The clean session's first scored +225,926, which Jakub handed to the
  prepared one: *"ok, one of my zoos got return +225,926.00 … try to at least find a better one"*.
- **10:52 and 15:12.** *"concider rewriting the codebase if needed, there might be alot of balast"*; of our bot
  adapter: *"is it hindering performance. should we rewrite it?"*
- **Round 1, 13:48 to 17:47.** Each session got the other's best score as its target (*"btw, another model just got
  498k. Try more"* went to Claude when Codex had 498,056), then the other's best file. The clean session's online
  ridge (R1-C1, 554,347) went to the prepared one at 16:17. Its R1-C5 (595,442) went back at 17:12: *"take a look at
  this one strategy_claude_best_595K.py … can you improve on top of it?"* The clean session's next versions became
  R1-C9 to R1-C12, the final ([lineage](../RESULTS.md)).

## A model that learns

- **Sat 16:49.** *"ok, but the best model was learning along the way right? in that case, could we completely switch
  our strategy and focus on those models?"* Measured on round 1's tape, R1-C1 made 554,347 as uploaded and 293,328 with
  its learning switched off. The online ridge became the core from round 2 and carried all four rounds.
- **17:12 and 17:16.** *"can you try something quite different but still a lerner model?"*; *"look again through the
  wiki from the literature, if there is something to be tried with learner models?"* The agents tried an event-time
  forecast and learners from the prep's literature ([`IDEAS.md`](../IDEAS.md), "Learner ideas from the wiki's
  literature"). None made the final.

## Speed and Rust

- **Sat 09:31, before the playground.** *"plus there is queue priority, so maybe being super fast should help"*.
- **10:06 and 10:52.** *"plus what if we rewrite their engine in rust too?"*; *"worth rewriting the their new engine
  in rust"*. The port of the organisers' simulator was committed at 11:03 and matched it byte for byte at 11:08
  ([`rust/README.md`](../rust/README.md)).
- **16:02.** *"does the speed of the model matter? seemed like yes. could we speed it up?"*
- **Sun 00:56, after round 2.** *"when you were running the things, was it python / rust or both? IMO we should have
  used more rust"*. At 01:25 he asked for it as a standing instruction (*"worth adding anything to claude.md? like try
  to keep it and run rust code"*). From round 3 on, every candidate was chosen in Rust and checked once in Python
  before its upload. Later he pushed for more: *"what are those python processes? could they be in rust"* (01:54),
  and *"the 14 cores and rust coudl probably do a lot of stuff. we have almost 3 hours"* (09:04).

## How the tapes were made

- **Sat 15:20, round 1.** *"the private and public data are different, but same lenght and probably from the same
  distribution. could we perhaps take a look at the whole dataset (the csv) explore how the engine works and from
  that create a perfect model?"* A generative model of round 1's tape was committed at 15:50
  (`experiments.generator.tape_gen`), but it only tested candidates on more draws.
- **Sun 00:51, after round 2.** *"ok, back to the idea of reverse engineering the generator. you looked into it
  before, but turns out that it is a really good idea. fist make a proper plan and how it could be used."* This
  produced the plan ([`GENERATOR_PLAN.md`](GENERATOR_PLAN.md)). Its first phase ran at 01:10
  (`experiments.generator.gen_identify`) and found the hidden price, its impact, the regimes and the jumps. At 01:15
  came R3-F1, a filter of the hidden price as three features of the ridge. On the server the filter was worth
  +149,769 (+20%, R3-F3 against R3-B1), the largest single gain of the event.
- **01:10 and 01:11.** *"so after we have a legit generator, we can even use it to generate more data right and then
  train our model on that?"*; *"should we do here both the generator improvement and also the model improvements? or
  shoudl those be separate sessions? its sort of 2 connected loops"*. At 02:15 he had a prompt written for a separate
  generator session ([`GENERATOR_SESSION_PROMPT.md`](GENERATOR_SESSION_PROMPT.md)) and ran it in Codex from 02:26. At
  03:58 he narrowed its job to the three things the filter models. Its generator ranked six bots in the real tape's
  order (rank correlation 0.94), but no filter built on it beat the original on the real tape (*"sad"*, 05:03).

## The field

- **Sat 18:52, after round 1.** *"if you open chrome using the extension and there open
  https://arena.qminers.com/dashboard/leaderboard then from that you can probably on the graph of pnl and time find
  how the winning strategies differed"*. All 61 curves were read off the chart. Every team earned in a near-straight
  line, and the winners had a steeper slope with less variance: better fills, not bigger bets. To the Codex session
  he wrote *"probably other strategy was used at least on the 1st place. not just a good parameter set"* (18:48) and
  *"remember that round 2 could be quite different"* (19:04). It was: round 2's tape made every round-1 maker lose.
- **Sun 00:57, after round 2.** *"again. open https://arena.qminers.com/dashboard/leaderboard in browser and
  investigate outhers strategies"*. The winner had made about 148k in one 25-second step at a price jump, over the
  position limit. *"what if we try to do smth like that in combination with the generator?"* (03:50). The over-limit
  jump bets lost on our simulator ([`IDEAS.md`](../IDEAS.md), "Burst sizing on R2-L9").
- Rounds 3 and 4 were read the same way (06:30). Every round's curves are in
  [`field_curves.json`](../data/arena/field_curves.json), drawn in the README.

## Our own curve and the explorer

- **Sat 22:41.** *"also anything worth exploring on the UI web tool from the organizers? imo some jumps could be worth
  it."*
- **23:05.** *"the spread goes quite wide before the drop. are the models taking advantage of that?"* Measured that
  night, the wide spread warned of volatility, not of direction. In round 3 the generator work found the same widening
  in new orders announcing jumps about 2 s ahead, and R3-S2 stopped quoting on it. The labels the organisers
  published after the event show a thinning of the book before every one of the 410 bursts
  ([postmortem](postmortem.md)).
- **23:36.** *"take a . look at the PNL graph of the submitted L3. there is a few places where it looses. is it
  possible to smoth those away? and maybe increase the profits?"* The dips were 3-4-second jumps against a full
  position and slower grinds. An exit after an adverse jump lost on every tape, so the dips were the cost of the
  bursts that paid. His next question, *"ok, was there some model family which was not explored properly?"* (23:47),
  found quotes switched by regime. That became R2-L8, which quotes only in calm markets: +826,778 on validation,
  +22.8k over L3.
- **Sun 04:13, round 3.** *"can you properly look at the stats of the PNL curve and then the orders the spreds etc.
  there are some places where we were loosing"*, then *"try to reduce the spread paid on f5"* (04:21). The loss
  anatomy found that 70% of the PnL was the position's mark-to-market, with the worst losses from jumps against a
  full position. The guard rule built on it stayed off ([`IDEAS.md`](../IDEAS.md), "R3-F3's loss anatomy").

## Statistics before models

- **Sat 20:48 and 21:14.** *"maybe also try more statistics approach and resserach on the data if possible"*; to the
  Codex session: *"can you try and look more into the data itself? the statistical distribution and many stats and
  really deeply think about it and create some models based on that"*. Its study
  ([`ROUND2_DISTRIBUTION_RESEARCH.md`](../codex_repo/docs/ROUND2_DISTRIBUTION_RESEARCH.md)) proposed twelve strategies, all of them
  makers.
- **21:57.** *"can you write some response to the agent which wrote … ROUND2_DISTRIBUTION_RESEARCH.md on what the
  issue was"*. The answer said that makers lost on the server's validation tape while takers paid. It went to the
  Codex session at 21:58 with the paths of our best taker. The taker with liquidity and young-order features that
  came back became R2-L1: +771,770 on validation, against +490,359 for the taker it started from. Without quotes it
  became R2-L3 (+804,018).
- **Sun 01:27, round 3, and 07:15, round 4.** *"btw, also try very different strategies. those might work on the
  dataset. or perhaps first do some proper statisical analysis"*; *"can parhaps do first a proper statistical analysis
  of the dataset?"* Round 4's pass gave the flow and depth features of R4-W3, which lost 22k on validation against
  W2.

## Distrusting a good number

- **Fri 23:41, the night before.** *"can you preparte some proper prompt for tomorrow once the 1st round opens? imo
  it should include a lot of stuff, like make sure it is not overfitted. show multiple trained models with different
  pluses/minuses. … perhaps a looping prompt. with verification"*. Five minutes later the round prompt had its
  improvement loop: one experiment per iteration, each checked by a verifier that didn't build it
  ([`KICKOFF_PROMPT.md`](day/KICKOFF_PROMPT.md), "The improvement loop").
- **Sat 13:09.** *"you can then run some expensive grid search to find the best one btw, but dont remember about
  being carefull on overfitting"*.
- **16:22.** *"just a note: dont use sample_v2, only the round1.csv, they should be different, and the important is
  the round1"*. From then on, candidates were judged on the round's own tape only. Later: *"is it safe? not too much
  overfitted?"* (17:28) and *"remember that round 3 can have completely different data then round 2. so just dont
  pick based on round 2 only"* (Sun 01:14).
- **19:28, round 2.** *"i will wait a bit for the 1st submission. due to the public x validation x test data split
  now. i might wanna use the submissions for better models"*. The first uploads showed makers losing on the
  validation tape (R2-E2 −41,499, R2-V2 +71,864) and takers paying (R2-M2 +376,082, R2-T1 +485,667). In round 3,
  R3-B1, the bot without the filter, measured the filter's worth on the server. *"we only have 5 submissions left, so
  i would be a bit carefull"* (22:24).
- **Sun 04:47 and 07:02.** *"can you now validate the F5 the best model. go line by line if there are no bugs?"*. On
  a round-4 number: *"round 3 no?"* and *"please validate this one. run it again. and make sure it is againts round 4
  data. that seemed too quick"*.
- **10:14 and 11:01 (Codex).** *"i want you to audit the other sessions top models. mainly the r4_W2_warm10k.py"*;
  *"check what all has been tried. some experiments are missing"*. The audits ([`ROUND4_W2_AUDIT.md`](ROUND4_W2_AUDIT.md),
  [`ROUND4_EXPERIMENT_AUDIT.md`](ROUND4_EXPERIMENT_AUDIT.md)) found four faults: a feature mask that dropped the wrong
  columns, a profit gate that flipped the sign of direction-free inputs, a switch that silently started the model
  cold, and a 64-sample queue that could drop labels before they matured. So several round-4 ideas recorded as failed
  had not been tested as recorded. *"so the param search and others were not being tested properly?"* (11:09).

## The model itself

- **Sun 01:41.** *"since we will have the generator and have way more models, could we train a bigger model, which
  would require more weight and runtime, but woudl not require online learing, so we could jsut pretrain it and upload
  if it makes it into the 1MB limit?"* A pretrained MLP and boosted trees forecast round 3's held-out quarter slightly
  better, but gained only 75 in PnL there and lost on other rounds' tapes. Trained on generated tapes they failed
  ([`IDEAS.md`](../IDEAS.md), "A pretrained forecaster").
- **07:05 to 08:29, round 4.** *"what ways did you try to bootstrap it. think of more ways"*; *"or maybe could there
  be a mechanism where at first it doesnt trade?"*; *"perhaps try and tune the warm setting on f5?"*; *"i dont want
  quick change on start to cause some issues"*. The result was R4-W2: the ridge started from round 4's public-tape
  statistics at a prior weight of 10,000, uploaded at 08:34 and kept as the final (+1.8k over the cold start on
  validation).
- **09:38 to 10:52.** *"what about something like kalman filter or things like that"*; *"since it is all linear
  regression, wouldnt it be possible to calculate the exact best weight directly from the training data?"*; *"what
  about some data normalization / standartization before pushing it to the model?"*; *"would it be worth exploring
  stuff like boosted trees or SVM? either pure online or pretrained or warmed like the ridge regression?"*; *"did you
  try something like the p value of the features?"*; *"did you ever testsomething with moving averages / RA / sarima
  models?"* In that hour the agents tried a Kalman drift state on the filter (R4-D1), random Fourier features in the
  online ridge (R4-RFF1) and removing features by group (R4-A1). None beat W2. The forecast was saturated, and the
  binding constraint was the 100-lot limit, not forecast quality. His reply: *"ok, how do we improve that?"* (07:43).

## Over the limit

- **Sat 13:33 to 16:03, round 1.** *"did you try some strategies which do hit the penalty but could make more
  overall?"*; *"brainstorm some crazy strategies, which would allow for it"*; *"imo some crazy trades with the 1000
  order limit with the penalty could be taken"*. In round 1 they didn't pay: every cell of the over-limit burst taker
  lost ([`IDEAS.md`](../IDEAS.md), "Crossing the limit on purpose"), and Přemysl's branch rejected its breach policies
  too. In round 2 the winner showed that it could pay at jumps (above). Our attempts, built on round 2's final, lost
  on our simulator's thin post-jump book.
