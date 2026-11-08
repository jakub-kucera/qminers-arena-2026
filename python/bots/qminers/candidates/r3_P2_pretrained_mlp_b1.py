"""R3-P2 (8 Nov, round 3): R3-P1's stacking on R3-F3 (R3-B1 + FILTER: R3-F1 plus R2-L8's speed-switched one-lot quotes,
QUOTE_SIZE 1 only while the 5-s |mid change| rate is below QS_RATE 2.5 ticks/s); the same 39 ridge features as R3-F1,
so the same pretrained MLP. PRE = 0 with NUMPY_RIDGE = 0 is R3-F3 exactly. R3-P1's notes follow.

R3-P1 (8 Nov, round 3): R3-F1 plus a PRETRAINED forecast of the 400-ms mid move, a small tanh MLP fitted offline on
real and tape_gen v2 tapes (`python/experiments/day/pretrain_forecast.py`; its weights embedded below by `pretrain_forecast
embed`). PRE = 1: stacked, the frozen forecast is the ridge's 40th feature, so the online ridge re-weights it per tape;
PRE = 2: it replaces the ridge's forecast (the ridge is not fitted); PRE = 3: a fixed blend PRE_BLEND x the ridge's +
(1 - PRE_BLEND) x the frozen one; PRE = 0: R3-F1 exactly. The MLP's inputs: F1's 39 ridge features and 14 cheap extras
(PreExtras: the spread, touch and second-level sizes, the mid's 1-s and 10-s absolute moves, the time since the last
wide spread and the last mid move, that move, the market takers' signed sqrt flow and largest order over 1 s, the
filter's probability the latent is a tick or more above / below the mid, and its unclamped gap). It is evaluated at
each ridge observation (every 20 ms) and again at a 1-tick spread when the forecast is within PRE_GATE of a take.
The notes of R3-F1 follow.

R3-F1 (8 Nov, round 3): R2-L9 (the Huber-ridge taker) plus a latent-price filter's features in the ridge. The filter
is a hidden-Markov filter over the generator's latent reference bid lb (experiments/day/latent_filter.py, the offline
copy): new market bids land at lb - k and asks at lb + 1 + k (k 0/1/2 with FILTER_PI), clamped one tick off the other
touch; lb random-walks at FILTER_RATE ticks/s each way; a market taker's filled lots move it FILTER_IMPACT x tape_gen's
impact table. Features: gap = E[lb] + 0.5 - mid, gap*|gap|, the posterior sd. FILTER = 0 is R2-L9 exactly. The notes of
R2-L9 follow.

T2-derived structural taker hypothesis: t2_liquidity_features. Original source supplied by another session. No validation score for this alteration; strict all-live reservation accounting retained.

Round-2 hypothesis; performance on round-2 data is unknown.
Uses only current/past public information and causally matured labels.
"""
from collections import deque
from math import exp, ceil, floor, isfinite, log1p
import base64

import numpy as np

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

QS_RATE = 2.5  # quote one lot only while the 5-s |mid change| rate is below this (ticks/s); else pure taker
TAKE_MAXSPREAD = 1  # the forecast take fires only while the spread is at most this many ticks (99: no limit)
TAKE_ROOM_LIVE = 1  # R2-T2: the take's room is EXPOSURE - pos - every live same-side order's lots (0: R2-T1, EXPOSURE - pos)
FILTER = 1  # R3-F1: the latent-price filter's three features in the ridge (0: R2-L9 exactly)
FILTER_W = 8  # the filter's grid: lb within bid - W .. bid + W
FILTER_RATE = 2.0  # the latent's random walk, steps a second each way
FILTER_EPS = 0.01  # the likelihood floor (an insert the model cannot explain)
FILTER_PI = (0.55, 0.39, 0.06)  # P(k): an insert k ticks behind the latent touch (round 1's offsets)
FILTER_IMPACT = 3.0  # x tape_gen's impact table (round 1's 5-s mid move by size); round 2's best 3
FILTER_SQRT_C = 0.0  # > 0: Phase 1's rule instead of the table, a fill of q lots moves lb FILTER_SQRT_C * sqrt(q) ticks (r1 0.024, r2 0.0365)
FILTER_DEPTH = 6  # only inserts within this many ticks of the previous touch are observed
PRE = 1  # R3-P1: 1 stacked (the frozen forecast as the ridge's 40th feature), 2 replace, 3 blend, 0 R3-F1 exactly
PRE_BLEND = 0.5  # PRE = 3: the ridge's weight
PRE_GATE = 0.3  # re-evaluate the frozen forecast at an event when the forecast is within this of the take threshold
PRE_CLIP = 3.0  # the frozen forecast's clip (ticks)
NUMPY_RIDGE = 1  # the online ridge's sums and solve in numpy (the same sums to the bit, LAPACK's solve; ~20% faster); 0: F1's pure-Python loops
# BEGIN PRETRAINED WEIGHTS (written by `uv run python -m experiments.day.pretrain_forecast embed`)
PRE_SHAPES = ((53,), (53,), (53, 32), (32,), (32, 16), (16,), (16, 1), (1,))
PRE_BLOB = (
    "FXbGur6Xb7tslzE7HPFKuzARRzugW5i69msMO+z757vX9iU749EsO+QYGTn1BAw59NGGOidN8jpp0/Y6IiK0uX1xAzs6sew6qn4nOTyYFTuhQKi5"
    "Kp+cuKYjDrsAAAAAPhA3N3ho6LgAV8w6AAAAABmrjbfWFJ46fEi3OUK47bo6ksk61aEyu1JBBrt+9Ha5r+WwuRRXmLr4FqQ+uWWUPy4UFTyHaCNA"
    "oyXaPgXO4j76Yys//lsuP2UcgLsgJzi8ZoMLu6Zlhz5iFIc+DoH6uRY3k7r4/vM/bY5XP/IbzD8IoYM/LKWhP9X2KEDdPvk/cuv/PoBs7z+A3Ow/"
    "IcqEQM0qgECc42JAzLsfQNtGHEDuQEBBtbynP2lmqD9KVfJA0c6gPwPBK0EUE6FCtN9pQAAkdEn/opNEE8TJQj8eaT8AJHRJpIaFQ/cf7D/a7ShA"
    "k0QtQLUrPkDfsqA/KR7VP1UYSD9IeqA/h33VP1ySxkAVhw9AcwPqPqSPHEAG6uA/qHj8PwWNpD+/Nqg/pjLwPzfv1D7cVmE/H5IoQH6oKEDTtZ8/"
    "cc4IPziXPL6a5qI8DQ2+O8gu2LwPZtO9MDMZvTetbb1TF4E+518bvh5zF756cIC9VOYUPfsMmr7g2gS+qLIRvgo9r75cvbU9fkcSvnuRMT5Z3oo+"
    "yk8+PsVDjT7CmBc+U0Z9vShzMz42C1A91W5dvufaob6UWo++iKZQPtDlUb4VTRc9WXZ6u5n+1T1viNC8MsLWPO+fjr5nr589OhvSPCfc4j2JEve9"
    "TwiCPdp7Ij4Z7+y8MZ61vWwlvT1qj5w+5KK+PYrINT5wrQI9fmXiPbAZvL00SbI8drV9Pv/i0rziY1U+jLDlPKl7rbxr6Su+IrazPe7FP7zbEme9"
    "4w4GPxArmT0d/Gw9YUebvaBncj4ohfc7dkI6u3IKWb6H0KW9NuTXPSTxsj2GfFg8DqyHPuevh71AFwq+N4MbPv4eWj0xQms+LTyOPVdZGL4lZa28"
    "cBddvth/q727mQI+m7IcPuVVWD6b2jO+CuyePqxWWTzswsE9nNCtvbwpCz4Q5SY9nh8aPh1vFzuCKMK9GM8IvvSBTr6lzNw8EV0FPqTaJrwl0Ye9"
    "MI3bPchkIb4jM8y9oAkEPpII2b4MtuM84nOOvQpYWjwM3UQ9N3c7vd3Eyj0dDj29/LlyPV2oDD68jZg9efKgPTD+FT7H2R4+aaMQvdic3L1Nsh29"
    "Th0uvSzwCr7Qvog9AeOEO1c6Fb6I/s69pxV5PA+96zwUX0o+uPjePRCBMz2QkS4+NqM8Pp5Hs77qLwy9hQk2vZRj7roXGRg+waDGPdDaIz4M8r29"
    "BhYGvmWd+r0DPYk9nTAePits37tnWM474Sotvdv0p72y1cM9PIo5viqH0T1pCk28+MEhvALSf76ZtcC9QyOrvLNe5jwu+Dk8x1eFPltiH767OzO9"
    "joNfvkKUTj1QL0Y7xms6Pg9Aqr147K89ou0/vZwG5T3M5Hu9mRYYO0qb+j25SDS+xP/4vNcGWzmifKu9nKH+PdVLir1717Q82PqfPMqxcby5+LM9"
    "GZn8vXAhqzsg35a9AR0IvvX4ND7mwgm9gPBGvfpw/z0VJnC+5PGrvKwhpb3wJYY96v40vX1/kDv4pW6+bvIRPuLjiD3H75A9HHJrPS3KLb2eJLW9"
    "LIrlPW2J272HVUY+wABdvW/rkDzX2oU97esCPka8mb3PXX29ieDAvcqXHD6Q3qK8eaA9vgBSvbzCZok9PJ9TO64fCj4RjcK6oQATPdfHDb5F/ly9"
    "ltWNPPqGFr6IjdC6a/FAPqlHAr32OUy+EqGOvvh7nbzRIAG/OdmbvMYcnbwoNpq8BtjXPLpAgr2GKh477ifKPKsd5r3COp8+i8UuvQrs873Cc+Q8"
    "aiZWPW+hQj44r+C9gJQ6PuHSzj6mJR09cFK6PcMRO70HnIs+TRl3vZTtM71YXDK+xBQ7vQ0fabz4Qwg+ozu1vSJJnDzUTVW+qHRFvZK3nj5i0Co+"
    "dmpDvTDZR74NRRW9K5WiPelCCj7hruu9uYrivajD8D1zSlq9gOiePQRDI7o+jxy7Gtm+vgXtLD2I4mO9P/YuvurpHD14hMU9YQQTvo+TYr60ZeI9"
    "o/ofPg39NL6a1HE9wHaqvUrqYz0X8xa+nioJPQb2Jz6SMDM+3BhYPYH1xb6VSjI9TiwOvWmUrD3f6ZC98hdkPQLG57w1ZMo9fNm4vVgCBj6CqUq9"
    "njOuPXOqpr183x6+WL+KPRF9yryrxEk9x9LxvGkRVj0jKfi95apqvG7Epj37O7C9UeV2OjEfGL61M809leUIvtNyQb06eem9VE5EPidZ2r0Bewe9"
    "uTOivJTTgL1yFk++lmWZPSDsTr5n8bC99OL7PdhtmT6/3Zu94fT5vGiEhb6qZPC8wtq7vv82Xz50/+M9THwIvW+5Yj38a1S+HoievYfSAj6EEe67"
    "9ddzvVvgIj1nPA4+AhXsPD40A76TBBQ+sY8TPutPoL3Tg2W8CkeEvlT4YL19Ug89FSQKvtOXizyPwle8X4CavSmaNT0Zy4Y9N71fvN0vNL4fcBY+"
    "GKl8uHHgBzyRM7m9Cbc+viVUlb3gMAy9f3revf3ZdL50A7e9uNTvuqTrUL0v0Du+7PbGPO2xoT5bU269pt1CvcSm3r31Lns9svEyvm4w6r1ExM29"
    "ZQG2vAL4Mb1Rl7S9+Hk4PWhjIr7oAlE+eAESvuu50j1khn480/PkPSw0i73FGTe9hqJ0Pb9zGD5LX428x8jGviBWG73Otho+BADXvO8s8T3zQ289"
    "gqX5vKgRUr7CwhE+d7InPoWlELwWRL8+s8H8vZnLjb0pqh4+KtSEPXtBUL13ZZ89IPrzvbYFjzzLU+M9yQ46vuEgrD6rZQW+V6c4PqtCxrxFyaM9"
    "sQpxvdW2Hz4CJrA9JboNPm/+oT6bXMk9S8iePLodTD1kHzw9hKbTPP43gr2zdNo9ewMWPtaIlTwQQ4e9XiwovmTqAb5fCl49xTg8PdJRbj0H5Dy+"
    "pGUrvkJyML5TzkU+5cU+O78Wwj3YcsO96oIzvLjNub2ZhNC9jOVbvih2zrwTLu48WBvaPf4xrL2sjjO85BImvczylbxNadC+8rKtPZLVHLu6U3Q+"
    "/IJGPIdUXL0xFRQ9DdL/Pbrccr0AbGU9tifVvXMQxDyn0Qu+OXIsvJCKsL1wRgs+EF0SPSSVuL4Whue8cdkYPoA7oL1uDXQ9WLcRPlyc2r0TcUW+"
    "roYIvpnF4z1e73W9ScQsPHXVn707YQo+5eKmve9ocD6znXw9xG7ovdRDnD2a6bs9+iYVvhJpZD6L+ic+xQShPDuqib0M0Aw+FboFvroFEr1d9+S9"
    "7MWYPUcPmLycimc+hHLkvNneZLxz9Jk+E0RKPSU1Gz2ZaSg86JjdPtb0Hj44mG28Ta1LvpwNlryrmjO+UJiZvsg+Fb6uBqq8DAqsPnFE8zvKyKk9"
    "nuxTva9flL3Dspg8OVc6PUxGnb3dj8Q+7vzrvRweDT5UHR48uJ7mvUMozr3N7ZC9pyUtvnxIQT5gQ9W9y3TtvQivnT21cJS7BoUqPuBwHzsYDIA+"
    "Pt9cPnyUXT2N8Eg+vU82vhRSpj3d74W9yORzPMjtF75A9Zg9Y51HPuh04z262hS+ZTqUvZa1nz1+F8u9UC74veF2xD1Re6K9FyoYPjrY7r3pIuA8"
    "XU+7PRBvT74ZAB4+ZKlVPvZrij0Ab5G9gOI1voGnabw6zw4+7jSkPDAWpTvrd1u+L+VWPlYLJr4+zzQ+KQVWPdkxDj4As1Q9HuMcviqwdD1weSw+"
    "xwV3vr/m+DtBMcu9WMk8vUwwfbtTcjS+ug5BPqOLFr59Ozu+834zvpWDMz4WkgY+Bq2UPrOHgDzn5og9xd+JPTXKG75WexW+Dq2cvTPfg779iP48"
    "ZZxqPq5GnL3nWx89igxRPqqfbbxWjwM8Yy8Xu4tMNz4gzIW9JFGrPgjq1r0uvbM9hP9xvLI5gL0UaKI78bXLuw19I76bUIk9sxrsu8/NCr2aowk+"
    "Q8RMPXyEhzx8QQU+8T4pPoo5J7s7ycw9RMjqvejnDD1W7cW9EEE9PbVDor0yP+e8tV+0PYvZWL3423e8ixGAPSszpj2KwAI9X3wRPX/fWr1udyg9"
    "vvYVvQljAT6y3Bq+TSOKviK7Gz6Mnry7MBm2vKzK3D30FQ49g+38vfBrOr3TWzs9PHm8PVZc3T2BHwy+5P1DPibFaT7i+Jq8iMoHPt5tmb3pKyC+"
    "1sMgvmoesT1DW4a7vciSPECz9r1m3jq8IsVaPcJ+BL0jcKw9BN3zPVYZRb7k50q9Xrsavg1kLj094/C98YSSvtNUJr3c8Py9/q7YPbhoHD2TbFI+"
    "OGGYvj6AFb2XKuq9HuNJPTzxsT0TmqU8Nal0vk1GMLtcSVw9hoEPPjSEGz4zgoU+5nZQPmL6oz4eSkU9LpkbPi8rE74PqOS9GCKCvrih+b3ialG+"
    "R01zvuVeAj41kMqAJOEPAd4GjgBeDj2AQ6tggHdueQAC34KAZ8NaAGeF5gCIIQQBuVxEgG5TmwC7RDqARMopgJ5MLIE42ZqANAV4ALkgH4G3VqaA"
    "gxAogdKojYDoX3oAoKHfALXWuwCwlysAPhQqgfhwAoC4UcEAGJt1AGAPG4BYHSIBcnEagfCBrzrEoJo9h5xZPYl6sz39Vh6+A1DuvAkJJb6Hm16+"
    "Vuz0PV0F9b0aMAa+GVnwvVuF+L1Pb/a9lbbNvDySEb2t2bu9nT42PGNFlr1ZTc26jQMVvhvbpbwiTXo9WPWIPbYlN768SDA+YmKxPA9ioL0xbhG8"
    "FEtwvZLTJD2zxqi8oD0UPGaVKD0F2kU9FYjuPYEv3DzARC++CnnovdN5DLyKPeC9fkELPi7efD1esMS8pzNAPqWhG74x3jG8cZCfvP54C71ZKBI9"
    "eDsvPq1bnz2kwyE++BrpvQvnFz2+awq+ZMBVPLbkY77sYnc9ohTKvMgSub3E84q8BI0JPkM7Cj0H7Ey9GOZCPW/SQ71cYL89T39zvoP1nDxVEwk+"
    "yzq1u9jLnTqvZT0+wtXpPdub9735qza+5HqNvTIruL0Harg8I6GiPca11j0c+DM85letvX+0rL1a6r897UV/Pp58hj613489205dPMvffz6A1KO9"
    "iJMGvt/qWr6vJ5W9LvSCPXLYJwE4/8kAPORhgEIGzYCU84yBxgSNAJ5hdIATFiCBMFlvgD0dCIEqcZyAoMLogMRJ6wB82UwA+1s7gTAYBAAwZksA"
    "+Pp1AHhU+YCw5ZgAiCX/gLDOKIFExwoBQHqUgCLlngAophWAxLBeAHYKN4E6cFOAkEzQAK7ZAQHhELeAk7Q8PbW9Rb3GHqC9UZKrvBhLlLpDkEk+"
    "oz1CPgimrb2u+pU9rzMyPUDOGjx5wvU9kLRMPf2Bdj1aYTQ9xd6wO7Sbm70JwQ09IxKXu4kUnb0mgO09AHU/PdWKHL5LAn49HI+OvejiOb5+eTg9"
    "v7SUPWmBh72/qJo9pmDovd0Dn7u4YDu+Jt9jvbSBHj0NSx++wV4FPSqalz5RHjG9wCXvvRh7kL0MCVO+QXMmPSocsz3Rnoe9NZZVvof5DD1wNoS7"
    "F6asPhXVCb3ckQe+yrBJPrOzrb7drT4+HgRgvTElOjxS6gW9VTQtPcT+AL35oSI+ws1svuiolzwB6he+/+gEPquw+LwEHPu8Z3tzPlA3M7wYNly+"
    "PESmO15bH72zKxw9yDcovh84+r3IkpC5wPT4PVDDxbzP/Ni8CMkGPhX/L74sszU+IRtAPhAsZ71Dho8+DogsPh0e3j1NTnO+dR7ePBDEqL0HL5G9"
    "EAhnPmk71r0Da289Yg0TvgaT0z1jV1a+uTZtvRjjS76f7tC9yarQPmKeWb0J8po+5LBrPcO3M70N9am8JxjHPOE9ID5naKI8qrC4vQexKr5F3My9"
    "X0MMPiYaFL6Cucc8373SPM4gRT0dWAI6cIpdvsfMkr1QBN08CPimPWnMeTzAKLE9pd6VPvrwrL7KNno+YTJnPerQtjp1Xqk9nVcwPmH4EL5tJPs8"
    "e9ixPrRCAL6v3G090W2Wu8yjNb1jLgc8RPa3PbSn5b13/o4+M8gfPi3tCL4SS5Q9FyVEPUYGzrwh3t68NR+9vbFCUz2iOe+95+ZEPrFWDL5ADCA+"
    "kaJCPl4l8byaiL8+uWapvOBnGL6jZ6I9zWL2PQOqEb4nPAS+7L8svoo8AL9jZk++wddqPRIukb1Fz7C+lXucPveoe748+eQ88r1YvkH4gj097pS+"
    "M+M4vvuYQL2kzxy+4GkaPTT9z77PyM+9s/+HvrlOvzurXdA+f54YvuDaWj5puJC+IGc3vWgJsb4T+e+7mId+PdNHHr4uf5g++8mzvXtnOj7YIMg9"
    "a0FePsVJ4jtrzRK92guyPnDOYj64a+e933EwPeQq1D1YNvW9/WaZvGIn971SmsM9savFvaZypD3atU8+f2OAPaVCJD0ZNPs9Oy7YPhPCwz7DNr28"
    "KjUePuLXcb6ZzcM963vfvpwoT77ZNn09q2VgvunwUT5ftmm9Ncf1Pee9Xb3PFUc+xta7vfaE/T3yydc7Gr6VveZHAjwlLBA+dJJNvm1tQj0HjDO9"
    "ukD+vDtl6zr+T/69mKECvaZagL1Zc7s8oAgSPqq9ET0UFWA92d52vtheGT74BBQ9lE1RvSQpJb5q0eM9qavDPdg1OD6zOmc9rBXAPZd2WL5rPVG9"
    "hI6rPtkcnb1mqAC9za3avt4ZTL66Ej0+10PBvlZHmj3dPDm+HzbYPTHeID44Q0a+9Cu8PCFaKDyge0o+fywyPmMPlT3rjgI8FlOtPkA2eT01CRC+"
    "B3NTvrTkz72cBWI+jgmfPjODKD78SGy9NLcOvaKt+D1UCMW82a1LPW1MbT6SVqY+wfQwPntOVD2+Zpq+YDitPvzGhr72naW+x4Rjvrt/qb5HH2a9"
    "wV1kvcyLfT5dL6Y+b6XlPQ/YPb4LGcY9HiZ8Ppfwl77+iWe+j6CEvB39hL5cwvu74ncPPnn6Ir65g40+rxvlPSibAL1ddCs+in3JvSicMr2YI1G+"
    "TcGrPAvftTxTgL687YpEupIKtL0n1BY9SKyZvajOj7y9b4Q9E356vMDKyrwgRVQ+n4EpPlL9X7y3Kxs+pGU6vc1KM74hfUs92OaUPq1FtD2tUis9"
    "Oda5vGQTfb10WBu9rwP/vTjimb0B/zi8VDZVvelV0b2ejSw98WVgPevpM73IiHG9mgOpu33hXj0PxGa9nNGhvckg1r2dabi7Kav0vbRxZr62Toc8"
    "byHNvXDSmb65rh49HykNvaOLTbzWRqo8SXWNvpIEl77bCOI7SrZpvUXAxj2x0RM+y5e8vBGd/b1dHv88GxfyPe0GvT6wKco8aNRcu5olJL7La0e9"
    "WtwmPvSXhDwHFng8MDKCvgYQSr1VHKq9NOuPPHu6dD2GTRQ+oMOMPYGGbT6INGk+uv0bvvwucjy50p8+Bre6O3c5OzyqVyM+b/1PPSseB75o/7A8"
    "4PgWvsCOTL1wjkg9S22GvXb4ab2R0eA888tXPax9jjtNsZ09B/elvM2WdL2pMwo8nhhZPV02+zsz0bO9NWs2vbS/tj3n2yQ9Q0cTvO7Neb05DpU+"
    "uTJDPRF3uj5/nkc9n7/hu+tPAj6AmXM95Ss3PcCNkb3sGoA+GVJpvNjPGTxG02m6+5xNvb1wc732+RY+atk6vXcElj5l8Y48wD0rvD9Nmj3LXio+"
    "pN+LPoMyAb8kim49UE+fvcc4KL0p5Jm94Ae1va6DY7zVlLY833mhPRvnKD5L3ii9iHS2vZUZLL5pgq0+pDBAvf8wfz6zO789PA5RPhkXMj4At3i+"
    "jhD2vaRXwTpw67U9/uHGvAl6bD7MZ8c+U+MZPDyoW73GP6M9UNJRPUfmFT1NhRO+6i3xvuKI9Ly0DtA8aZ57POJi8zxajpy+Y6g8vT8xQT7uO8i8"
    "qnzxvamIjT1MNIk8T9GePWIuej42nIk9yP8dP4ziCj1MQrY9KmBJvXn/GT4JVJg9WW+1vqO0/Dwt8Uq9AVuSvTbX3r1SPuI9hXvCPRtVuTsVm/E8"
    "RI1TPaihgD1WxHq9BtEbvuUtoj1GjXq9nfsbvhi8Q7vX8lc96xPtPS9gtb0KDvU9mzw9vZ1f5z0HNXi9OMEOPd2WOL4xur89YjNxPQUuwT26x04+"
    "kyGmvYNGGD1w9rm88YGnvOXrSb47StI8WoMaPiM8pj6dNEU9UpMOPC02DrsnDIq8a24QPkuLv7zhBre9wGdUvdHx8719ody8vJ5CPVF8Gr10AnW8"
    "fcbmPcOEY77epLo9DeQ+vecqfTxvaMG88bJevIB8tr3eZLW8nnzxvSDvjbxgSHW9+hp6vqVnYj11Zn0+qIz+vSJiBT55C1O99bCJvkzB/T0Wcow6"
    "TDLivCIXIrxO3Ia8HsJwve2xDr7n2um8g0YQPmpKYDkHcDy9Ap3svXey0L00OCK+DUL0vaXAjzumTj++TScNPWb7nTwVYVK+TQ69vjd6/r2G4YU+"
    "p17+PNbxejm5xlS9wJu6vk2uJj7VyVC+nx/SPZpVfb2txFK99br/PFb4rrwn6Fk9xuEoPrrdqjvM5oW+Mp1kvMRwRbv9zkQ9MZOuvkV2rr3yf6u7"
    "KgsJvgaJAD2o96Y8VpvtO2Veir6Ubkm7opapvvo9Fr5vuLG+A7fnPYtyoz3r7R69lNs2vi85Y76a0Zg+FCqfPoNBzD3FI3Y+D9CevSngGj7J3GW+"
    "NCrvvcNUpL0y02K9sqnAPTqFIz43GTA+7Q/RvRaw1r1dsM07KQYzvoCSUD1wx4w+4006PmJ2Sz4bmM+9xJPcPeu3fz0PEoY+cDJwPunggD0i5Ec+"
    "HrAbvvJ/jL6fqhm9+om7PiQfrD2Rwce9iu7JvTvzyDs6H9y9oQU6vQJpe73I11k+cb6GO1BoLb60Em0+wFq2vJJCVDxxfEo+7/eFPRU7DT4bU5m9"
    "PXaIPd83vbylzJi9UboavS90GL6cphI+eJq1PRUHFjwux7A9P2gLvvK2cT4DyKG+o00SvoUzxT1JPRk+XA61vZbvHj21d6Y++pqTvfZEb736rEu+"
    "WacvPitBQb4Q8BO9zq0zPYBBu7ub2cE9MTWeO1WMI77lYwm+pgIQvcdQ8LyQJB0+/s6jvVNDPb1DhAC+Cgc+Pg7XJL5fjoI+u9wCvqxHBz0QjJ4+"
    "uNGHvjj097zvoa892JlyvQs9JT7CCLG+DlygPQbggz27nO67Q3ixvvDFlr7ZIAq+rNEHvU73vj4SzPA9aVY5PQ8PZD1vfBQ+QJynPoe6Pr472Ak+"
    "AVqUvYbYwr7cd089mQPTupM9jT4bnWi+wG8Vvsu1Az5vX2W+jtvvPEE43b2R9rw+kBF0vULO8j264KS9nt2SvjCzVT4DKBq9YKaoPS7AWL7jmMK9"
    "lPKQve21Pz5fOE4+0bsEvvcEFD7d8oG+Ll2sPNNXC722x7i8dOIDvRtugL5OagS+kfECPvESFD4CYaA7Y8sPPt2REL7uwsm8l95YPkLjED7QyOG9"
    "NZRVPN5Jub64nIS9w6l4Pen/s71UV1s9cWWSvUvAQz69J4E9fQMbvLA8071pize9fT4cvQ7ZtT1Pdvq9Y1G7vQHqxb00pNA8uL74vbq4xD1P+jy+"
    "Fy9bPg4DETxKHFo5pYqRvuxZnr1IBYY+DH9tPCRAhT9V1yA+e2UFPpEeNz21whQ/gB3HvFhIhTtHmrI+KB9oPivfcz5ncYq+sXnfPFBkYTzXnwQ/"
    "qHp7vl9ZZT7gR7Y+4DayvamogLydaMA+ktIZP/LY573FfJw8z358vqmuU77gj7C+pPcbPEcMkD77w+O9cHCjPeBN271r4zE+p43fvVhd6L4OMsW+"
    "TjugvsI3C75DHhU+SJVLPFThzb0uym89yhVRvvuwuT0ls6s9A27uvFssnL7rXwo+JzFMPm5s7D0lT3g9N4qVPKJoDD3AyrO+eCP7O8R1r7w7dAC/"
    "tuqFPmVeJD5dndO99nDvu6qRkb6bX6a9zZs3vYfvxz70tOu8da0WvqAJKr5Mdqk9XjWbPYEL+z1GXiq+pcURPchJUL4ARkC+PVSzvSlHiT51e06+"
    "1ZJoPYexkz7F7GG9lvWGvvJh5D26NAq+ry6WPsc1ubzjx1y+OSbGPWq0iT515xm+GezZPq4Ti734OCg+23lMvWRt6D1WHcS+cgk3vlFb57382bS8"
    "xBeFPPw5az6H11+9SHgrvlC5mTuVa9W9fFkKvviedr7h7Qy9BmkuPZzt5T3Qfpe8GUkgvqdaQD0mTUk+wNltvPsAhL7Za5a+CLuDvmbgHr4+mze+"
    "LyaqvRPhLL7Xq3E+/1F1PmP7Mz6oGc++A3tqvrcykb6wbIE+MJGEvi8jFL5XHM49L83uPg963DxlNAk9Fha5vjd5nj7Pdkc8bIievioVgD3Nzhu9"
    "00WmPfG1Vj1Le1I+QOqovTi7pT72lYs+YJ+APncfVT10H1I+lrIdvrq9TL4KKuW9ctm7PEBGHjxNBRg+mMSFvUUDqz2xuiy+/b6lvbxtFz4HLkG+"
    "0GGVPjp/ZD7VQp0+/CbsvVY+TL5HAaq9w0gmvGL0rL2m3qk+WG+LvKncHb7mWhg+eXxzPnZM972eM8Q9EYJSvICnkjxs4JO9XXZxvmsazD6Q9Eu+"
    "NHbtvapDqz2miIQ8O7l2vgmEt71ZyK699DH8uz8dUT5c4FW+9vXgvXSNhj56oS29BYoYvlxnAr7eXOA99wqEvjimXD7NcvS+p0G2PsQlTr7VrIy+"
    "8Kasvqx0qz5XPE4+6esJvyKx6r0Wh7u8tLeYvpVMXz7qAQC/HFjNPrEMAr59Pu890geaO5rhLL4y/Vc+csSRvcmoP75EIPG9gLhWvlGiJL7bslY+"
    "+YLPPf5QhTzxWFG8gmc0vUENijwwbxM9w+0SvKRTjL0xh4y9wgqxvvtJhz676YQ+R/Bcvkg4Mj5SM6K9j/juvU4jE74Vvq89bvS/vhKwkL2BGba+"
    "yaVgPDncVr1eWIy+UCZ7PqyChT4m+rm91+N4vUDBaT2Q87Y9UhNQPtzmor3I+oE+tZSDve09L718CKw+SI7eOqcUyL7GH0g9sXdnvswHmr4XZ6G9"
    "uXwxPadbJ7z1tLS+ZtA7PUQGg7xiJFa+r3ipvqiF1r6BWrq+G18UPnFnaz0418U9Yk4zvoh7gDu4310+BFvzvNTLwj0AbrO+G6KKPbHmzL3Mywy+"
    "dJiIPvkmRr7MDRO+rWqDPvF38704CoS+Eu1ePLVrVD11Uom+xFdsPteOAb03y9M8wfk5vV/Ugr2IF48+IGRMPuUbiL1KPay92PBDPeYF871+XPu8"
    "TSnLvCp3rT3JVLA8ypYovnieQT65R7w+EO3cvRyYOb1A/1Q+vZw8Pl5FV74ebs8+980QPtRpiL1qObG+lJWLvvyThz4rEzU9YwuDvt/BjL5FYuW9"
    "ukDkvkKMMb74Er++LgjduRer6bxrNwK9/ROfPtZ10zxEXS48plvbPTLbUL5ItWM+6gXxPZ+5rT1hKwe+Q6qKvID0hD26Lle+HT8uPb34az51j668"
    "yNaavZ5UbD6+oZE+zlgAPgdVujxaagm+lKfoPcZGqj6jZX6+ANwFPmHkAD4saYQ+e/K1vC87tL4AE/s+mQ8evvVaFz58ODq9PWeVvc3LJT4bXwc8"
    "jvalPUhl8TuQNDs+ZHg3PqV87D1z5Is+PRuWvuyEaj2Rkwy9oik3PoxlfL1qK3G8mqMmvvHoVj7BiV49sG+FPqqu5b3g6lk+i7Arvk8m6rwTF388"
    "89yNviNDZD44RZe9obOevrf+F76Rz4w+n4yFvWK1x71wtYu+3+YKPob1Fz6vb28+IpFEvgO4TbxEIzq+YchmvhDECz4Kv+E8Z+eiPjePAT9bBq49"
    "LVfkvVjiFj6nkAi+WaSePZhIt75uEiw+GmDkvb2vqj5EXqU9m9q0vRuTAL2M7ha+gSgvPmVIML5U/bS+gMVlPmpF6D4Qno0+GycnvuOo5T0UFoQ+"
    "RiKmvLAsB771SL28y0kHPO2OBL70k4y+95oPPteLwb23LIe+htiZvsZIe73QTY4+zBehO2hqST4sr9e+eK0Dvqt9EL48NpS9CuCCvTL3AL4Dp7O+"
    "fygBPl27S75E/EQ+r9gvvu/whz2n0pW9qjU0Pn648z30Fds+sIkjvSsfYL5gkJC+Eempve+nZz3ZbwS+q3jRPiyqUj6JfEq+fE2qve/VFL6+FMO8"
    "WKoZvsgzwz7tw7e8pFS6vZimTj4DRaa8Ww1uPfmIfj72WhE+MtFgPT/yB7xws5+9gNqBPndDvL2ox4c+x9YUvas+jz4UGCa8QH57vFGOTT24SoE+"
    "jcwpPu1aeL6BZtA8l1HWPsmyQr7YTxM+7k/UPeeCVr4dy5K+8pVmvlBCbj6yZUI9h47/PWEkOb7lO18+w7YQvvwQrr0B6Eq+kO5uvin9zT7HgPK8"
    "sdhQvil+i74c0s09A/gPPgo06zyfMMY9Fix6vUgCbL4xJZu+xGTzOzUAmT7Cipi+I9ugvTz7qr3vYgY+34DGvSFKhb1oUi2+4ZUVPpMFOD7sgwu+"
    "xFqLvfeQRjw3PWA9MbKTvl5HLT4cfJg96l0avgJa6ToFGUa9yghsPoZYMT/aoCK+BA+9vstauz6HQCo+uTcKP0Prij5+7Z2+RJrRveomXT5iV2Y+"
    "RYLJvhePDb8C1+q+4otCPnTOPb7kouy8"
)
# END PRETRAINED WEIGHTS
# tape_gen's round-1 impact table: (max lots, mean 5-s mid move in ticks)
FILTER_TABLE = ((10, 0.097), (30, 0.111), (60, 0.161), (120, 0.254), (250, 0.349), (500, 0.468), (1000, 0.704), (10**9, 0.903))


class PreExtras:
    """The frozen model's 14 extra inputs' running state, updated on every valid book event before the forecast (the
    same code as experiments/day/pretrain_dump_bot.py's AExtras, which made the training rows)."""

    def __init__(self):
        self.t = None
        self.mid = None
        self.v1 = self.v10 = 0.0
        self.t_wide = -10**12
        self.t_move = -10**12
        self.last_move = 0.0
        self.fsq = 0.0
        self.fbig = 0.0

    def update(self, now, bid, ask, trades):
        mid = (bid+ask)*0.5
        dt = 0 if self.t is None else max(0, now-self.t)
        self.t = now
        if dt:
            d1 = exp(-dt/1e6)
            self.v1 *= d1
            self.v10 *= exp(-dt/1e7)
            self.fsq *= d1
            self.fbig *= d1
        if self.mid is not None and mid != self.mid:
            move = mid-self.mid
            self.v1 += abs(move)
            self.v10 += abs(move)
            self.t_move = now
            self.last_move = move
        self.mid = mid
        if ask-bid >= 2:
            self.t_wide = now
        if trades:
            lots = {}
            for trade in trades:
                if trade.taker_owner != 'market':
                    continue
                row = lots.setdefault(trade.taker_order_id, [1 if trade.book_side == 'ask' else -1, 0])
                row[1] += trade.quantity
            for direction, q in lots.values():
                self.fsq += direction*q**0.5
                if q > abs(self.fbig):
                    self.fbig = direction*q

    def features(self, now, bot, snapshot, bid, ask):
        mid = (bid+ask)*0.5
        bq = aq = b2 = a2 = 0
        for orders, touch, sgn in ((snapshot.bids, bid, -1), (snapshot.asks, ask, 1)):
            q1 = q2 = 0
            for order in orders:
                if order.owner != 'market':
                    continue
                d = (order.price-touch)*sgn
                if d == 0:
                    q1 += order.quantity
                elif d == 1:
                    q2 += order.quantity
                elif d > 1:
                    break
            if sgn < 0:
                bq, b2 = q1, q2
            else:
                aq, a2 = q1, q2
        up = dn = 0.0
        raw = 0.0
        p = bot._lf_p
        if p is not None:
            base = bot._lf_base
            m = 0.0
            for i, v in enumerate(p):
                g = base+i+0.5-mid
                m += v*g
                if g >= 0.5:
                    up += v
                elif g <= -0.5:
                    dn += v
            raw = max(-10.0, min(10.0, m))
        fb = self.fbig
        return (min(5, ask-bid),
                log1p(bq)-log1p(aq),
                (log1p(bq)+log1p(aq))/5.0,
                min(20.0, self.v1)/5.0,
                min(200.0, self.v10)/50.0,
                min(10.0, (now-self.t_wide)/1e6),
                min(5.0, (now-self.t_move)/1e6),
                max(-5.0, min(5.0, self.last_move)),
                max(-50.0, min(50.0, self.fsq))/10.0,
                (1 if fb > 0 else -1 if fb < 0 else 0)*log1p(abs(fb))/5.0,
                up, dn, raw,
                log1p(b2)-log1p(a2))


def _pre_load():
    """The MLP's arrays from PRE_BLOB (float32, base64): mu, 1/sd, then (W, b) per layer."""
    if not PRE_SHAPES:
        return None
    flat = np.frombuffer(base64.b64decode(PRE_BLOB), dtype=np.float32).astype(np.float64)
    out = []
    pos = 0
    for shape in PRE_SHAPES:
        size = 1
        for d in shape:
            size *= d
        out.append(flat[pos:pos+size].reshape(shape))
        pos += size
    return out


class PassiveStrategy(BaseStrategy):
    IMPACT_HORIZONS=(500000,)
    HUBER_DELTA=6.0
    FEATURE_COUNT = (39 if FILTER else 36)+(1 if PRE == 1 else 0)
    HORIZON_US = 400000
    OBSERVATION_INTERVAL_US = 20000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 100000000000
    POSITION_LIMIT = 100
    QUOTE_SIZE = 1
    REQUOTE_US = 0
    EXPOSURE = 100
    DEAD_ZONE = 0.18     # R2-E1: 0.3
    INSIDE_TH = 0.3
    SKEW_K = 0.025
    FLOW_CUT = 1.1
    CANCEL_FREE = 0.0    # R2-T2: an order being cancelled counts in full toward EXPOSURE until the cancel lands (R2-T1: 1.0, free)
    HEDGE_TICKS = 10
    HEDGE_STALE_US = 100000
    TAKE_EDGE = 0.15
    TAKE_SZ = 200
    TAKE_GAP_MS = 50
    TAKE_MODE = 0   # 0 any, 1 only to reduce, 2 only to open or add
    TAKE_INV = 0    # TAKE_MODE 1: the least |inventory| to reduce
    TAKE_THRU = 0
    KEEP_LOTS = 20  # 0: off (R2-E1)
    KEEP_TH = 0.3

    def __init__(self):
        super().__init__()
        self._impact_time=None
        self._impact_net=[0.0]*len(self.IMPACT_HORIZONS)
        self._impact_volume=[0.0]*len(self.IMPACT_HORIZONS)
        self._impact_frame=()
        self._qs_mid = None
        self._qs_t = 0
        self._qs_rate = 0.0
        self.inventory = 0
        self.cash = 0
        self._orders = {}
        self._distribution_time=self._distribution_mid=None
        self._distribution_seen={}
        self._distribution_fresh_count=[0.0]*8
        self._distribution_fresh_value=[0.0]*8
        self._distribution_frame=((),())
        self._hedge_id = None
        self._cached_bid = self._cached_ask = self._cached_time = None
        self._known_market = {}
        self._new_counts = [0.0]*4
        self._new_values = [0.0]*4
        self._cancel_net = self._cancel_mass = 0.0
        self._new_quote_time = None
        self._second_group_net=[0.0,0.0,0.0]
        self._second_group_volume=[0.0,0.0,0.0]
        self._second_group_price=[0.0,0.0,0.0]
        self._second_rest_count_net=self._second_rest_count=0.0
        self._desired_buy = self._desired_sell = None
        self._desired_time = None
        self._observations = deque(maxlen=64)
        self._last_observation_us = -100000
        self._last_fit_us = None
        self._last_label_us = None
        self._labels = 0
        self._mass = 0.0
        self._xx = [[0.0] * self.FEATURE_COUNT for _ in range(self.FEATURE_COUNT)]
        self._xy = [0.0] * self.FEATURE_COUNT
        self._weights = [0.0] * self.FEATURE_COUNT
        self._fast_mid = self._slow_mid = None
        self._model_time = None
        self._ofi = 0.0
        self._ofi_time = None
        self._previous_touch = None

        self._last_action = {-1:-5000, 1:-5000}
        self._last_us = None
        self._net = self._volume = 0.0
        self._invalid_since = None
        self.queue_ahead = {}
        self._take_last = None
        self._qp_touch = {1: 0, -1: 0}
        self._qp_d = 0.0
        self._lf_n = 2*FILTER_W+1
        self._lf_p = None
        self._lf_base = 0
        self._lf_t = None
        total = sum(FILTER_PI)
        self._lf_pi = tuple(x/total for x in FILTER_PI)
        self._lf_cum = (self._lf_pi[0], self._lf_pi[0]+self._lf_pi[1], 1.0)
        self._lf_moments = None
        self._pre = _pre_load() if PRE else None
        self._pre_x = PreExtras()
        self._pre_f = 0.0
        self._pre_evals = 0
        self._xx_np = self._xy_np = None

    # The latent-price filter (R3-F1): a probability vector over lb = _lf_base + i, i < _lf_n.
    def _lf_advance(self, t):
        if self._lf_t is None:
            self._lf_t = t
            return
        dt = t-self._lf_t
        if dt <= 0:
            return
        self._lf_t = t
        a = FILTER_RATE*dt
        if a < 1e-9:
            return
        if a > 0.3:
            a = 0.3
        p = self._lf_p
        n = self._lf_n
        keep = 1.0-2.0*a
        q = [0.0]*n
        prev = 0.0
        for i in range(n):
            cur = p[i]
            q[i] = keep*cur+a*(prev+(p[i+1] if i+1 < n else 0.0))
            prev = cur
        q[0] += a*p[0]
        q[-1] += a*p[-1]
        self._lf_p = q

    def _lf_recenter(self, bid):
        n = self._lf_n
        shift = bid-FILTER_W-self._lf_base
        if shift == 0:
            return
        if abs(shift) >= n:
            self._lf_base = bid-FILTER_W
            self._lf_p = [0.0]*n
            self._lf_p[FILTER_W] = 1.0
            return
        p = self._lf_p
        q = [0.0]*n
        for i in range(n):
            j = i-shift
            j = 0 if j < 0 else n-1 if j >= n else j
            q[j] += p[i]
        self._lf_p = q
        self._lf_base += shift

    def _lf_trade(self, direction, lots):
        if FILTER_SQRT_C > 0:
            m = FILTER_SQRT_C*lots**0.5
        else:
            m = FILTER_IMPACT
            for top,value in FILTER_TABLE:
                if lots <= top:
                    m *= value
                    break
        if m <= 0:
            return
        whole = int(m)
        frac = m-whole
        p = self._lf_p
        n = self._lf_n
        q = [0.0]*n
        for i in range(n):
            v = p[i]
            if v == 0.0:
                continue
            j = i+direction*whole
            k = j+direction
            j = 0 if j < 0 else n-1 if j >= n else j
            k = 0 if k < 0 else n-1 if k >= n else k
            q[j] += v*(1.0-frac)
            q[k] += v*frac
        self._lf_p = q

    def _lf_insert(self, buy, price, bid, ask):
        p = self._lf_p
        n = self._lf_n
        base = self._lf_base
        eps = FILTER_EPS
        pi,cum = self._lf_pi,self._lf_cum
        total = 0.0
        if buy:
            clamp = ask-1
            if price >= clamp:
                for i in range(n):
                    d = base+i-clamp
                    v = p[i]*((eps+(cum[d] if d < 3 else 1.0)) if d >= 0 else eps)
                    p[i] = v
                    total += v
            else:
                for i in range(n):
                    k = base+i-price
                    v = p[i]*(eps+pi[k] if 0 <= k < 3 else eps)
                    p[i] = v
                    total += v
        else:
            clamp = bid+1
            if price <= clamp:
                for i in range(n):
                    d = clamp-1-base-i
                    v = p[i]*((eps+(cum[d] if d < 3 else 1.0)) if d >= 0 else eps)
                    p[i] = v
                    total += v
            else:
                for i in range(n):
                    k = price-1-base-i
                    v = p[i]*(eps+pi[k] if 0 <= k < 3 else eps)
                    p[i] = v
                    total += v
        if total <= 0 or not isfinite(total):
            self._lf_p = [1.0/n]*n
            return
        inv = 1.0/total
        for i in range(n):
            p[i] *= inv

    def _lf_observe(self, now, snapshot, trades, current):
        """Feed the snapshot's market taker fills and its new market orders (against the previous touch) to the filter."""
        bid,ask = self._cached_bid,self._cached_ask
        if bid is None or ask is None or bid >= ask:
            return
        if self._lf_p is None:
            self._lf_base = bid-FILTER_W
            self._lf_p = [0.0]*self._lf_n
            self._lf_p[FILTER_W] = 1.0
        changed = centred = False
        if trades:
            lots = {}
            for trade in trades:
                if trade.taker_owner != 'market':
                    continue
                row = lots.setdefault(trade.taker_order_id,[1 if trade.book_side == 'ask' else -1,0])
                row[1] += trade.quantity
            if lots:
                self._lf_advance(now*1e-6)
                changed = True
                for direction,quantity in lots.values():
                    self._lf_trade(direction,quantity)
        known = self._known_market
        for oid,order in current.items():
            if oid in known:
                continue
            buy = order.side == Side.BUY
            if abs(order.price-(bid if buy else ask)) > FILTER_DEPTH:
                continue
            if not centred:
                if not changed:
                    self._lf_advance(now*1e-6)
                self._lf_recenter(bid)
                changed = centred = True
            self._lf_insert(buy,order.price,bid,ask)
        if changed:
            self._lf_moments = None

    def _lf_features(self, mid):
        if self._lf_p is None:
            return (0.0,0.0,0.0)
        if self._lf_moments is None:
            m = s2 = 0.0
            for i,v in enumerate(self._lf_p):
                m += v*i
                s2 += v*i*i
            self._lf_moments = (self._lf_base+m, max(0.0,s2-m*m)**0.5)
        mean,sd = self._lf_moments
        gap = max(-5.0,min(5.0,mean+0.5-mid))
        return (gap,gap*abs(gap)/3.0,min(3.0,sd))

    def _pre_eval(self, features, now, snapshot, bid, ask):
        """The frozen MLP's forecast (ticks) from F1's 39 features and the extras."""
        arrays = self._pre
        x = np.array(features[:39]+self._pre_x.features(now, self, snapshot, bid, ask))
        h = (x-arrays[0])*arrays[1]
        n = (len(arrays)-2)//2
        for i in range(n):
            h = h@arrays[2+2*i]+arrays[3+2*i]
            if i < n-1:
                h = np.tanh(h)
        self._pre_evals += 1
        f = float(h[0])
        return PRE_CLIP if f > PRE_CLIP else -PRE_CLIP if f < -PRE_CLIP else f

    def _distribution_features(self, now, snapshot, bid, ask, mid):
        if self._distribution_time is not None and now-self._distribution_time<5000 and mid==self._distribution_mid:
            return self._distribution_frame
        dt=0 if self._distribution_time is None else max(0,now-self._distribution_time)
        decay=exp(-dt/200000)
        for i in range(8):
            self._distribution_fresh_count[i]*=decay
            self._distribution_fresh_value[i]*=decay
        seen={}
        counts=[[0.0]*4 for _ in range(2)]
        values=[[0.0]*4 for _ in range(2)]
        touch_counts=[[0.0]*4 for _ in range(2)]
        touch_volume=[0.0,0.0]
        young=[0.0,0.0]
        age=[0.0,0.0]
        age_mass=[0.0,0.0]
        far_count=[0.0,0.0]
        far_value=[0.0,0.0]
        max_size=[0.0,0.0]
        for side,orders in enumerate((snapshot.bids,snapshot.asks)):
            touch=bid if side==0 else ask
            for order in orders:
                if order.owner!='market':
                    continue
                distance=abs(order.price-touch)
                first=self._distribution_seen.get(order.order_id,now)
                seen[order.order_id]=first
                if distance>4:
                    far_count[side]+=1
                    far_value[side]+=order.price-mid
                    continue
                q=order.quantity
                group=0 if q<=10 else 1 if q<=50 else 2 if q<=200 else 3
                counts[side][group]+=1
                values[side][group]+=order.price-mid
                if distance==0:
                    touch_counts[side][group]+=1
                    touch_volume[side]+=q
                    max_size[side]=max(max_size[side],q)
                    age[side]+=min(2.0,(now-first)/1000000)
                    age_mass[side]+=1
                    if now-first<=100000:
                        young[side]+=1
                if order.order_id not in self._distribution_seen:
                    k=2*group+side
                    self._distribution_fresh_count[k]+=1
                    self._distribution_fresh_value[k]+=order.price
        self._distribution_seen=seen
        odd=[]
        even=[min(10,ask-bid),min(10000,sum(touch_volume))/1000]
        for g in range(4):
            b,a=counts[0][g],counts[1][g]
            odd.extend(((b-a)/(1+b+a),
                (values[0][g]+values[1][g])/(1+b+a),
                (touch_counts[0][g]-touch_counts[1][g])/(1+touch_counts[0][g]+touch_counts[1][g])))
            cb,ca=self._distribution_fresh_count[2*g:2*g+2]
            vb,va=self._distribution_fresh_value[2*g:2*g+2]
            odd.extend(((cb-ca)/(1+cb+ca),max(-10,min(10,(vb+va-mid*(cb+ca))/(1+cb+ca)))))
            even.extend((min(40,b+a)/10,min(80,cb+ca)/10))
        odd.extend(((young[0]-young[1])/(1+young[0]+young[1]),
            age[0]/(1+age_mass[0])-age[1]/(1+age_mass[1]),
            (far_value[0]+far_value[1])/(1+far_count[0]+far_count[1]),
            (max_size[0]-max_size[1])/(1+max_size[0]+max_size[1])))
        even.extend(((young[0]+young[1])/(1+sum(age_mass)),
            sum(age)/(1+sum(age_mass)),min(100,sum(far_count))/10))
        self._distribution_frame=(tuple(odd),tuple(even))
        self._distribution_time=now
        self._distribution_mid=mid
        return self._distribution_frame

    def _impact_features(self,now,trades):
        elapsed=0 if self._impact_time is None else max(0,now-self._impact_time)
        self._impact_time=now
        net=volume=0
        for trade in trades:
            if trade.taker_owner=='market':
                net+=trade.quantity if trade.book_side=='ask' else -trade.quantity
                volume+=trade.quantity
        values=[]
        for i,horizon in enumerate(self.IMPACT_HORIZONS):
            decay=exp(-elapsed/horizon)
            self._impact_net[i]=self._impact_net[i]*decay+net
            self._impact_volume[i]=self._impact_volume[i]*decay+volume
            signed=self._impact_net[i];gross=self._impact_volume[i]
            values.extend((max(-3.0,min(3.0,signed/500.0)),
                signed/(1+gross)*min(9.0,gross/500.0)**0.5))
        return tuple(values)

    def _learn_np(self, now, mid):
        """_learn with numpy arrays: the same Huber-weighted sums element by element, numpy.linalg.solve for the fit."""
        obs = self._observations
        if obs and obs[0][0]+self.HORIZON_US <= now:
            if self._xx_np is None:
                self._xx_np = np.zeros((self.FEATURE_COUNT, self.FEATURE_COUNT))
                self._xy_np = np.zeros(self.FEATURE_COUNT)
            xx, xy = self._xx_np, self._xy_np
            while obs and obs[0][0]+self.HORIZON_US <= now:
                observed_us, old_mid, features, stored_forecast = obs.popleft()
                if now-observed_us > self.HORIZON_US+1_000_000:
                    continue
                elapsed = 0 if self._last_label_us is None else now-self._last_label_us
                decay = exp(-max(0, elapsed)/self.MODEL_MEMORY_US)
                self._last_label_us = now
                response = max(-20.0, min(20.0, mid-old_mid))
                residual = abs(response-stored_forecast)
                weight = min(1.0, self.HUBER_DELTA/max(1e-12, residual))
                self._mass = self._mass*decay+weight
                f = np.array(features)
                wf = weight*f
                xx *= decay
                xx += np.outer(wf, f)
                xy *= decay
                xy += wf*response
                self._labels += 1
        if self._labels < self.MIN_LABELS:
            return
        if self._last_fit_us is not None and now-self._last_fit_us < 1_000_000:
            return
        self._last_fit_us = now
        ridge = max(30.0, 0.003*self._mass)
        try:
            weights = np.linalg.solve(self._xx_np+ridge*np.eye(self.FEATURE_COUNT), self._xy_np)
        except Exception:
            return
        if np.all(np.isfinite(weights)):
            self._weights = weights.tolist()

    def _learn(self, now, mid):
        if NUMPY_RIDGE:
            return self._learn_np(now, mid)
        # Labels mature strictly after observation + horizon. Large gaps
        # are discarded instead of silently changing the prediction horizon.
        while self._observations and self._observations[0][0] + self.HORIZON_US <= now:
            observed_us, old_mid, features, stored_forecast = self._observations.popleft()
            if now - observed_us > self.HORIZON_US + 1_000_000:
                continue
            elapsed = 0 if self._last_label_us is None else now - self._last_label_us
            decay = exp(-max(0, elapsed) / self.MODEL_MEMORY_US)
            self._last_label_us = now
            response = max(-20.0, min(20.0, mid - old_mid))
            residual=abs(response-stored_forecast)
            weight=min(1.0,self.HUBER_DELTA/max(1e-12,residual))
            self._mass = self._mass * decay + weight
            for i in range(self.FEATURE_COUNT):
                self._xy[i] = self._xy[i] * decay + weight * features[i] * response
                for j in range(self.FEATURE_COUNT):
                    self._xx[i][j] = self._xx[i][j] * decay + weight * features[i] * features[j]
            self._labels += 1
        if self._labels < self.MIN_LABELS:
            return
        if self._last_fit_us is not None and now - self._last_fit_us < 1_000_000:
            return
        self._last_fit_us = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(30.0, 0.003 * self._mass)
        matrix = [self._xx[i][:] + [self._xy[i]] for i in range(self.FEATURE_COUNT)]
        for i in range(self.FEATURE_COUNT):
            matrix[i][i] += ridge
        for col in range(self.FEATURE_COUNT):
            pivot = matrix[col][col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            for j in range(col, self.FEATURE_COUNT + 1):
                matrix[col][j] /= pivot
            for i in range(self.FEATURE_COUNT):
                if i == col:
                    continue
                factor = matrix[i][col]
                for j in range(col, self.FEATURE_COUNT + 1):
                    matrix[i][j] -= factor * matrix[col][j]
        weights = [matrix[i][self.FEATURE_COUNT] for i in range(self.FEATURE_COUNT)]
        if all(isfinite(w) for w in weights):
            self._weights = weights

    def _hedge(self, now):
        if abs(self.inventory) <= self.EXPOSURE or self._hedge_id is not None:
            return
        if self._cached_time is None or now-self._cached_time > self.HEDGE_STALE_US:
            return
        sign = -1 if self.inventory > 0 else 1
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        quantity = min(abs(self.inventory)-self.EXPOSURE,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))
        if quantity <= 0:
            return
        price = self._cached_ask+self.HEDGE_TICKS if sign > 0 else max(1,self._cached_bid-self.HEDGE_TICKS)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now,0,0]
        self._hedge_id = oid

    def _take(self, now, signal, spread, bid, ask):
        if spread > TAKE_MAXSPREAD:
            return
        need = self.TAKE_EDGE + 0.5*spread
        sign = 1 if signal > need else -1 if signal < -need else 0
        if sign == 0:
            return
        pos = sign*self.inventory
        if self.TAKE_MODE == 1:
            room = -pos if pos < 0 and -pos >= self.TAKE_INV else 0
        elif self.TAKE_MODE == 2:
            room = self.EXPOSURE-pos if pos >= 0 else 0
        else:
            room = self.EXPOSURE-pos
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        if TAKE_ROOM_LIVE:
            room -= reserved  # R2-T2: every live same-side order (a one-lot quote, one being cancelled, the hedge) can fill first
        quantity = min(self.TAKE_SZ,room,self.POSITION_LIMIT-pos-reserved)
        if quantity <= 0:
            return
        price = ask+self.TAKE_THRU if sign > 0 else max(1,bid-self.TAKE_THRU)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now,now+1_000_000,0]
        self._take_last = now

    def _cancel(self, order_id):
        record = self._orders[order_id]
        if record[3] and not record[4]:
            record[4] = True
            self.cancel_order(order_id)

    def _preserve(self, oid, record, sign, price):
        # Keep a resting touch order's queue place: shrink it to KEEP_LOTS instead of cancelling it.
        if price is None:
            return False
        if not record[3] or record[4] or oid == self._hedge_id or record[1] != self._qp_touch[sign]:
            return False
        if oid not in self.queue_ahead:
            return False
        if self.KEEP_LOTS > 0 and sign*self._qp_d >= -self.KEEP_TH:
            if record[2] > self.KEEP_LOTS and (record[7] == 0 or record[7] > self.KEEP_LOTS):
                self.modify_order(oid, self.KEEP_LOTS)
                record[7] = self.KEEP_LOTS
            return True
        return False

    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        changing = False
        for oid,record in current:
            # A forecast take (record[6], its exemption's end) is not cancelled by the re-quote.
            if (price is None or record[1] != price) and now >= record[6]:
                if self._preserve(oid, record, sign, price):
                    continue
                self._cancel(oid)
                changing = True
        if len(current) >= 8:
            return
        if price is None or price <= 0 or now-self._last_action[sign] < self.REQUOTE_US:
            return
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        effective=reserved
        quantity=min(self.QUOTE_SIZE if self._qs_rate < QS_RATE else 0,self.EXPOSURE-sign*self.inventory-effective,
                     self.POSITION_LIMIT-sign*self.inventory-reserved)
        if quantity <= 0 or (current and quantity < 1):
            return
        order_id = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price, quantity=quantity, order_type=OrderType.LIMIT))
        self._orders[order_id] = [sign,price,quantity,False,False,now,0,0]
        self._last_action[sign] = now

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        elapsed = 0 if self._last_us is None else max(0,now-self._last_us)
        self._last_us = now
        self._impact_frame=self._impact_features(now,trades)
        second_group_decay=exp(-elapsed/1000000)
        for i in range(3):
            self._second_group_net[i]*=second_group_decay
            self._second_group_volume[i]*=second_group_decay
            self._second_group_price[i]*=second_group_decay
        self._second_rest_count_net*=second_group_decay
        self._second_rest_count*=second_group_decay
        if trades:
            visible={o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}
            arrivals={}
            for trade in trades:
                if trade.taker_owner!='market':
                    continue
                row=arrivals.setdefault(trade.taker_order_id,[1 if trade.book_side=='ask' else -1,0,0.0,0,0.0])
                row[1]+=trade.quantity
                row[2]+=trade.quantity*trade.price
                if trade.maker_owner=='user':
                    row[3]+=trade.quantity
                    row[4]+=trade.quantity*trade.price
            for oid,row in arrivals.items():
                direction,quantity,value,own,own_value=row
                group=0 if oid in visible else 1
                price=visible[oid].price if group==0 else value/max(1,quantity)
                quantity+=visible[oid].quantity if group==0 else 0
                weight=min(20,quantity)
                self._second_group_net[group]+=direction*weight
                self._second_group_volume[group]+=weight
                self._second_group_price[group]+=weight*price
                if group==0:
                    self._second_rest_count_net+=direction
                    self._second_rest_count+=1
                if own:
                    weight=min(20,own)
                    self._second_group_net[2]+=direction*weight
                    self._second_group_volume[2]+=weight
                    self._second_group_price[2]+=weight*own_value/own
        decay = exp(-elapsed/500_000)
        self._net *= decay
        self._volume *= decay
        for trade in trades:
            if trade.taker_owner == 'market':
                self._net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
                self._volume += trade.quantity
        bid = ask = None
        bq = aq = 0
        # Feed order is price-time order: quantity preceding our id is ahead.
        self.queue_ahead = {}
        for orders in (snapshot.bids,snapshot.asks):
            level = None
            ahead = 0
            needed = {r[1] for r in self._orders.values()}
            market_touch = None
            for order in orders:
                if market_touch is not None and order.price != market_touch and order.price not in needed:
                    # Prices are sorted. Only scan farther when one of our
                    # orders is at that price or beyond it on this side.
                    farther = any((p < order.price if order.side == Side.BUY else p > order.price) for p in needed)
                    if not farther:
                        break
                if level != order.price:
                    level, ahead = order.price, 0
                if order.owner == 'user':
                    self.queue_ahead[order.order_id] = ahead
                else:
                    if market_touch is None:
                        market_touch = order.price
                    if order.side == Side.BUY:
                        if bid is None:
                            bid = order.price
                        if order.price == bid:
                            bq += order.quantity
                    else:
                        if ask is None:
                            ask = order.price
                        if order.price == ask:
                            aq += order.quantity
                ahead += order.quantity
        if bid is None or ask is None or bid >= ask:
            self._previous_touch = None
            self._desired_time = None
            if self._invalid_since is None:
                self._invalid_since = now
            if now-self._invalid_since >= 50_000:
                for order_id in list(self._orders):
                    self._cancel(order_id)
            return
        self._invalid_since = None
        dt=0 if self._new_quote_time is None else max(0,now-self._new_quote_time)
        self._new_quote_time=now
        decay_new=exp(-dt/500000)
        for i in range(4):
            self._new_counts[i]*=decay_new
            self._new_values[i]*=decay_new
        self._cancel_net*=decay_new
        self._cancel_mass*=decay_new
        current={o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}
        if FILTER:
            self._lf_observe(now,snapshot,trades,current)
        for oid,order in current.items():
            if oid in self._known_market:
                continue
            distance=bid-order.price if order.side==Side.BUY else order.price-ask
            if distance>3:
                continue
            index=0 if order.side==Side.BUY else 1
            self._new_counts[index]+=1
            self._new_values[index]+=order.price
            if order.quantity<=50:
                self._new_counts[index+2]+=1
                self._new_values[index+2]+=order.price
        traded={t.maker_order_id for t in trades if t.maker_owner=='market'}
        for oid,order in self._known_market.items():
            if oid in current or oid in traded:
                continue
            distance=bid-order.price if order.side==Side.BUY else order.price-ask
            if abs(distance)>3:
                continue
            self._cancel_net+=-1 if order.side==Side.BUY else 1
            self._cancel_mass+=1
        self._known_market=current
        mid = (bid+ask)*0.5
        if self._qs_mid is not None:
            k = exp(-max(0, now - self._qs_t) / 5000000)
            self._qs_rate = self._qs_rate * k + abs(mid - self._qs_mid) / 5.0
        self._qs_mid, self._qs_t = mid, now
        spread = ask-bid
        flow = self._net/(1+self._volume)
        imbalance = (bq-aq)/(bq+aq)
        bn = an = bd_n = ad_n = 0
        br = ar = bd_r = ad_r = 0
        bd_value = ad_value = 0
        for orders in (snapshot.bids,snapshot.asks):
            for order in orders:
                if order.owner != 'market':
                    continue
                distance = bid-order.price if order.side == Side.BUY else order.price-ask
                if distance > 2:
                    break
                weight = min(20,order.quantity)
                if order.side == Side.BUY:
                    bd_n += 1
                    bd_r += weight
                    bd_value += weight*order.price
                    if distance == 0:
                        bn += 1
                        br += weight
                else:
                    ad_n += 1
                    ad_r += weight
                    ad_value += weight*order.price
                    if distance == 0:
                        an += 1
                        ar += weight
        count_imbalance = (bn-an)/max(1,bn+an)
        robust_imbalance = (br-ar)/max(1,br+ar)
        depth_count = (bd_n-ad_n)/max(1,bd_n+ad_n)
        depth_imbalance = (bd_r-ad_r)/max(1,bd_r+ad_r)
        depth_mid = (bd_value/max(1,bd_r)+ad_value/max(1,ad_r))*0.5-mid

        skew = self.SKEW_K * self.inventory/self.EXPOSURE * max(1.0,spread)
        if self._model_time is None or now-self._model_time > 10000000:
            self._fast_mid = self._slow_mid = mid
            self._observations.clear()
        else:
            dt=max(0,now-self._model_time)
            self._fast_mid += (1-exp(-dt/500000))*(mid-self._fast_mid)
            self._slow_mid += (1-exp(-dt/2000000))*(mid-self._slow_mid)
        self._model_time = now
        dt = 0 if self._ofi_time is None else max(0,now-self._ofi_time)
        self._ofi_time = now
        self._ofi *= exp(-dt/500000)
        if self._previous_touch is not None:
            old_bid,old_ask,old_bq,old_aq = self._previous_touch
            change = (bq if bid >= old_bid else 0) - (old_bq if bid <= old_bid else 0)
            change -= (aq if ask <= old_ask else 0)
            change += (old_aq if ask >= old_ask else 0)
            self._ofi += change/max(1,bq+aq,old_bq+old_aq)
        self._previous_touch = (bid,ask,bq,aq)
        ofi = max(-3,min(3,self._ofi))
        features=(flow,max(-5,min(5,self._fast_mid-self._slow_mid)),imbalance,
                  ofi,spread*imbalance,flow*abs(flow),imbalance*abs(imbalance),ofi*abs(ofi),count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid,count_imbalance*abs(count_imbalance),robust_imbalance*abs(robust_imbalance),(self._new_counts[0]-self._new_counts[1])/(1+self._new_counts[0]+self._new_counts[1]),
                  max(-5,min(5,((self._new_values[0]-mid*self._new_counts[0])/(1+self._new_counts[0])+(self._new_values[1]-mid*self._new_counts[1])/(1+self._new_counts[1]))*0.5)),
                  max(-5,min(5,((self._new_values[2]-mid*self._new_counts[2])/(1+self._new_counts[2])+(self._new_values[3]-mid*self._new_counts[3])/(1+self._new_counts[3]))*0.5)),
                  self._cancel_net/(1+self._cancel_mass),
                  max(-5,min(5,(self._new_values[0]+self._new_values[1]-mid*(self._new_counts[0]+self._new_counts[1]))/(1+self._new_counts[0]+self._new_counts[1]))),
                  (self._new_counts[2]-self._new_counts[3])/(1+self._new_counts[2]+self._new_counts[3]))
        features += (self._second_group_net[0]/(1+self._second_group_volume[0]),
                  self._second_group_net[1]/(1+self._second_group_volume[1]),
                  self._second_group_net[2]/(1+self._second_group_volume[2]),
                  self._second_group_volume[0]/(1+self._second_group_volume[0]+self._second_group_volume[1]),
                  max(-5,min(5,(self._second_group_price[0]-mid*self._second_group_volume[0])/(1+self._second_group_volume[0]))),
                  max(-5,min(5,(self._second_group_price[1]-mid*self._second_group_volume[1])/(1+self._second_group_volume[1]))),
                  max(-5,min(5,(self._second_group_price[2]-mid*self._second_group_volume[2])/(1+self._second_group_volume[2]))),
                  self._second_rest_count_net/(1+self._second_rest_count))
        self._distribution_features(now,snapshot,bid,ask,mid)
        young=self._distribution_frame[0][20]
        dispersion=min(3.0,self._distribution_frame[1][-1])
        features+=(young,young*dispersion,flow*dispersion,count_imbalance*dispersion)
        features+=self._impact_frame+(max(-3.0,min(3.0,self._impact_net[0]/(1+(aq if self._impact_net[0]>=0 else bq)))),)
        if FILTER:
            features+=self._lf_features(mid)
        due = now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US
        pre = self._pre
        if pre is not None:
            self._pre_x.update(now,bid,ask,trades)
            if due:
                self._pre_f = self._pre_eval(features,now,snapshot,bid,ask)
            if PRE == 1:
                features+=(self._pre_f,)
        if PRE != 2:
            self._learn(now,mid)
        if due:
            stored_forecast=max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
            if PRE != 2:
                self._observations.append((now,mid,features,stored_forecast))
            self._last_observation_us = now
        ready = self._labels >= self.MIN_LABELS or PRE == 2
        prediction = 0.25*spread*imbalance
        if ready:
            if PRE == 2:
                prediction = max(-2.0,min(2.0,self._pre_f))
            else:
                prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
                if PRE == 3:
                    prediction = PRE_BLEND*prediction+(1.0-PRE_BLEND)*max(-2.0,min(2.0,self._pre_f))
            if (pre is not None and not due and spread <= TAKE_MAXSPREAD
                    and abs(prediction-skew) > self.TAKE_EDGE+0.5*spread-PRE_GATE
                    and (self._take_last is None or now-self._take_last >= self.TAKE_GAP_MS*1000)):
                old = self._pre_f
                self._pre_f = self._pre_eval(features,now,snapshot,bid,ask)
                if PRE == 2:
                    prediction = max(-2.0,min(2.0,self._pre_f))
                elif PRE == 1:
                    prediction = max(-2.0,min(2.0,prediction+self._weights[-1]*(self._pre_f-old)))
                else:
                    prediction += (1.0-PRE_BLEND)*(max(-2.0,min(2.0,self._pre_f))-max(-2.0,min(2.0,old)))
        fair = mid + 1.0*prediction + 0.0*0.25*spread*imbalance - skew
        self._qp_d = fair-mid
        self._qp_touch = {1: bid, -1: ask}
        if abs(fair-mid) <= self.DEAD_ZONE:
            fair = mid
        buy = min(bid,floor(fair-0.5))
        sell = max(ask,ceil(fair+0.5))
        if spread >= 2:
            if prediction-skew > self.INSIDE_TH:
                buy = min(ask-1,bid+1)
            elif prediction-skew < -self.INSIDE_TH:
                sell = max(bid+1,ask-1)
        # Withdraw the side vulnerable to a persistent aggressive sweep.
        if flow < -self.FLOW_CUT or self.inventory >= self.EXPOSURE:
            buy = None
        if flow > self.FLOW_CUT or self.inventory <= -self.EXPOSURE:
            sell = None
        if (self.TAKE_SZ > 0 and ready
                and (self._take_last is None or now-self._take_last >= self.TAKE_GAP_MS*1000)):
            self._take(now,prediction-skew,spread,bid,ask)
        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now
        self._hedge(now)
        self._desired_buy,self._desired_sell,self._desired_time = buy,sell,now
        self._quote(now,1,buy)
        self._quote(now,-1,sell)

    def on_private_order_update(self, event):
        record = self._orders.get(event.order_id)
        if record is None:
            return
        if event.status == OrderStatus.ACCEPTED:
            record[3] = True
        elif event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self.inventory += record[0]*event.filled_quantity
            self.cash -= record[0]*event.filled_quantity*event.fill_price
            record[2] = event.remaining_quantity
            if event.status == OrderStatus.FILLED:
                del self._orders[event.order_id]
        elif event.status == OrderStatus.CANCELED:
            del self._orders[event.order_id]
        elif event.status == OrderStatus.REJECTED:
            # A failed cancel or modify can arrive after the original order
            # filled; unknown ids are ignored.
            if not record[3]:
                del self._orders[event.order_id]
            else:
                record[4] = False
                record[7] = 0
        elif event.status == OrderStatus.MODIFIED:
            record[2] = event.remaining_quantity
            record[7] = 0

        was_hedge = event.order_id == self._hedge_id
        if was_hedge and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._hedge_id = None
        if (not was_hedge and self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= 5000
                and event.status in (OrderStatus.CANCELED,)):
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)

        if was_hedge or event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self._hedge(event.timestamp_us)