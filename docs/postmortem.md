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

## Why our forecast worked so well

The mid's next 400 ms is mostly the latent catching up, and the order flow reveals the latent: where new orders land,
how big the last aggressive orders were. An online ridge regression on order-book features learns that mapping from
the tape as it plays, which is why one model family carried all four rounds. Adding a Bayesian filter of the latent
from where orders land (R3-F3) was worth **+149,769 on round 3's validation tape (+20%)**, the largest single gain of
the event: the closer the model got to the generator, the better it did.

## How far we got in reverse-engineering it

A first generative model of round 1's tape existed by that afternoon (`experiments.generator.tape_gen`), but only to test
candidates on more draws; we set out to identify the actual generator only in round 3, where it was harder: the
volatile regime and its jumps. By then our generator (tape_gen v2) ranked round 2's 14 validation uploads in the
server's order (Spearman 0.974), and its fitted parameters per round are in `data/arena/gen/`. As far as we heard,
other teams had reverse-engineered the simpler generator of rounds 1 and 2 already. The winner of rounds 2-4 appears
to have bet on the jumps: its round-2 curve gained about 148k in a single 25-s step where ours gained 18k.

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
  jump. Two families of episodes we never separated ("reserve" and "meta") turned out harmless: the forecast held at
  0.55-0.57 in both.
- **The forecast failed exactly in the bursts.** Its correlation was 0.27 and 0.10 in the two burst types and zero in
  thinning, the 2% of the tape with the largest moves: the part of the market the winners appear to have bet on.

## Why the prep did not transfer

We prepared for a month on IMC Prosperity data as a stand-in for an unknown API: several products, a market of bots
that react, market making around a fair value. The Arena was one instrument, a fixed tape that never reacted to us,
and from round 2 on a market where volatility per lot traded made resting quotes lose (our round-1 makers lost money
on round 2's tape, every one of them). What carried over was not the strategies but the habits: learn online from
the tape rather than tune constants, check every change on held-out data, and record everything (the prep repository
has that work).

## What we would do differently

- **Identify the generator in the first hour of round 1**, not in round 3: the hidden price, its impact and its
  regimes decide which strategies can work, and the filter that tracks the price was the biggest single gain.
- **Trust structure over small numbers.** Most local gains of 10-25k on the public tape did not survive the
  validation tape (all three such uploads in round 4 lost 16-28k there); the steps that held were structural: the
  taker (round 2), the filter (round 3), the in-flight cancels with the hedge (round 1).
- **Bet where the generator is predictable.** The first jump after a quiet spell was announced about 2 s ahead by
  wider placement; the winner appears to have sized up on jumps, while our bot stayed within the 100-lot limit
  everywhere (our own over-the-limit jump bets lost on our simulator's thin post-jump book).
