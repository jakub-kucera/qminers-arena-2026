# Postmortem: what the market was, and what that meant

## The tapes were generated, not recorded

The Arena's market was a replay: each round's public, validation and private tapes were fixed streams of order
inserts and cancels, our orders matched against them by the organisers' simulator (5 ms latency, a 100-lot position
limit with a 10,000-a-second penalty beyond it). The streams looked like a market, but by round 3 it was clear they
came from a fairly simple generator, which we identified from the tapes themselves (`experiments.generator.gen_identify`,
`IDEAS.md`, "The tape generator's structure"):

- **A hidden price.** Every new order is placed around a latent price that the visible mid only follows (round 1:
  1.03 ticks from it on average).
- **Deterministic impact.** Each aggressive order moves the latent by c·√(traded lots), permanently, with no random
  part on round 1 (c 0.024; 0.028-0.058 in rounds 2-3 by regime).
- **Two regimes and jumps.** Round 1 had one calm state. Rounds 2-3 switched between calm and volatile states in runs
  of 2-3.5 minutes, the volatile one with jumps of 3+ ticks (about 50-65 per 1,000 s, median 5-6 ticks, permanent);
  after a quiet spell, new inserts placed wider announced the next jump about 2 s ahead.
- **Uninformed flow.** Aggressive orders choose their side by a coin flip, with the same size distribution on every
  tape (median 60 lots, heavy tail).

A few common patterns plus noise, then, rather than a market of agents reacting to each other. In Jakub's words
after the event: the data was "a few common patterns with some noise and not really a market simulation", and the
market "was able to be basically easily predicted".

That was our reading during the event. The organisers' own description ([below](#what-the-generator-really-was))
corrects it in three places:
- from round 2 the impact followed a noisier law, and from round 3 it was partly transient;
- the jumps were a mechanic of their own, not part of the volatile regime;
- round 4's takers were informed.

## Why our forecast worked so well

The mid's next 400 ms is mostly the latent catching up, and the order flow reveals the latent: where new orders land,
how big the last aggressive orders were. An online ridge regression on order-book features learns that mapping from
the tape as it plays, which is why one model family carried all four rounds. Adding a Bayesian filter of the latent
from where orders land (R3-F3) was worth **+149,769 on round 3's validation tape (+20%)**, the largest single gain of
the event: the closer the model got to the generator, the better it did.

## How far we got in reverse-engineering it

A first generative model of round 1's tape existed by that afternoon (`experiments.generator.tape_gen`), but only to
test candidates on more draws; we set out to identify the actual generator only in round 3, where it was harder: the
volatile regime and its jumps. By then our generator (tape_gen v2) ranked round 2's 14 validation uploads in the
server's order (Spearman 0.974), and its fitted parameters per round are in `data/arena/gen/`. As far as we heard,
other teams had reverse-engineered the simpler generator of rounds 1 and 2 already. The winner of rounds 2-4 bet on
the jumps, as the organisers' review confirmed: its round-2 curve gained about 148k in a single 25-s step where ours
gained 18k.

## What the published data confirmed

On 9 Nov the organisers published every round's validation and private tapes, with the generator's hidden fair price
and its regime labels. Checked against them:

- **Our tooling was exact.** On the published private tapes the four finals reproduce the server's private scores to
  the unit: R1-C12 in the organisers' simulator, R2-L9, R3-F5 and R4-W2 in our Rust port.
- **The hidden price was real, and our filter found it.** Over round 4's private tape our filter's estimate was on
  average 0.43 ticks from the true fair price, against 0.65 for the mid. Knowing the true price exactly would have given
  the 400-ms forecast a correlation of 0.62 with the move; ours reached 0.50.
- **The regimes and the jumps were as we had inferred.** The labels name a turbulent regime (a quarter of round 4's
  private tape) and short burst episodes, and every one of the 410 bursts across the nine tapes is preceded by a
  3-second "thinning" episode: the precursor we had measured from the book, the spread widening about 2 s before a
  jump. Two families of round-4 episodes we never separated, "reserve" and "meta", turned out harmless: the forecast
  held at 0.55-0.57 in both. They are the generator's icebergs and TWAP metaorders (below).
- **The forecast failed exactly in the bursts.** Its correlation was 0.27 and 0.10 in the two burst types and zero in
  thinning, the 2% of the tape with the largest moves: the part of the market the top teams bet on.

## What the generator really was

The organisers' closing slides described the generator round by round, next to a review of the top five teams' code.
The table sets it against what we had worked out from the tapes. The labels in the published regime files use the
same names: `s2_thinning`, `s2_burst_A/B`, `s3_turbulent`, and in round 4 `reserve_A/B` and `meta_A/B`.

| Round | What the generator built in | What we had |
|---|---|---|
| 1 | A hidden fair price, moved by exactly √(volume) at each taker fill. New orders were priced off it, and book imbalance, signed √-volume flow over 1 s and queue position all carried signal | The same: √-impact with no random part, and the hidden price from where new orders land |
| 2 | Impact became a noisy law in V^0.55 and the cube root of the gap to the size-weighted mid, no longer exactly recoverable. Three new mechanics: S1, deep sweeps after one-sided flow; S2, a 3-s thinning, then an instant jump of the fair price; S3, a calm or turbulent regime (impact ×3.5, a wider spread, no precursor) | A √ law fitted by regime, the two regimes and the thinning as a precursor; the jumps folded into the volatile regime; no sweeps |
| 3 | Round 2's mechanics, plus shelving (a 2-ms ladder bot resting orders 2-7 ticks deep) and mean reversion (45% of the impact transient, with a 10-s half-life) | The ladders, in the generator session's model; impact treated as permanent |
| 4 | Round 3's mechanics, plus icebergs (a refilling 15-lot peak, with the fair price drifting away from it), TWAP metaorders (160-lot children every 0.5 s), a trending drift (an OU velocity, τ 3.5 s) and informed takers (their side follows the fair price minus the mid) | The drift and the informed takers, in round 4's generator fit; the drift as a Kalman velocity state on the filter (R4-D1), which did not reach the final. Icebergs and metaorders were never separated |

The review of the top five puts our best idea in proportion. All five estimated the fair price from new orders, with a
Bayesian grid, a Kalman filter or a regression, and all five told calm from turbulent time by round 2. So the filter,
our largest single gain, was what every top team had.

What set the pace was trading the S2 jumps past the 100-lot limit, into the room below the simulator's hard cap of
1,000 lots. Team 1 did it from round 2 and Team 2 from round 3. Teams 3 and 5 traded jumps within ±100 from round 3,
Team 4 only from round 4, and by round 4 all five went past the limit.

The rest was covered unevenly. Two of the five used round 3's mean reversion, two round 4's metaorders and three its
drift. None used the icebergs, the cube-root gap or the S1 sweeps, and none rested orders above 100 lots.

## Why the prep did not transfer

We prepared for a month on IMC Prosperity data as a stand-in for an unknown API: several products, a market of bots
that react, market making around a fair value. The Arena was one instrument, a fixed tape that never reacted to us,
and from round 2 on a market where volatility per lot traded made resting quotes lose (our round-1 makers lost money
on round 2's tape, every one of them). It also cost the first hours. In the playground the session working from the
prepared repository lost 7,598 with its first bot, while a second session given only the organisers' starter scored
+225,926, and round 1's final line came from the clean start. What carried over was not the strategies but the
habits: learn online from the tape rather than tune constants, check every change on held-out data, and record
everything (the prep repository has that work). [`decisions.md`](decisions.md) lists the calls Jakub made during the
event, from his prompts.

## What we would do differently

- **Identify the generator in the first hour of round 1**, not in round 3. Jakub asked for it at 15:20 in round 1,
  but the first generator only tested candidates until round 3. The hidden price, its impact and its regimes decide
  which strategies can work, and the filter that tracks the price was the biggest single gain.
- **Trust structure over small numbers.** Most local gains of 10-25k on the public tape did not survive the
  validation tape (all three such uploads in round 4 lost 16-28k there); the steps that held were structural: the
  taker (round 2), the filter (round 3), the in-flight cancels with the hedge (round 1).
- **Bet where the generator is predictable.** The first jump after a quiet spell was announced about 2 s ahead by
  wider placement. By round 4 all of the top five traded the jumps past the limit, while our bot stayed within the
  100-lot limit everywhere (our own over-the-limit jump bets lost on our simulator's thin post-jump book).
