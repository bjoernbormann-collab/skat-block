"""Walk-forward evaluation: calibrate on fold k (train), evaluate on fold k+1 (test), never the reverse."""
from .replay import run
from .calibration import Calibrator


def walk_forward(prices, signal, folds=8, **kw):
    n = len(prices) // folds
    cal, out = Calibrator(), []
    for k in range(folds - 1):
        run(prices[k * n:(k + 1) * n], signal, cal=cal, **kw)            # train: only updates calibrator
        seg = prices[(k + 1) * n:(k + 2) * n]
        r = run(seg, signal, cal=cal, **kw)                               # test: out-of-sample
        out.append((r, seg[-1] / seg[0] - 1))
    return out
