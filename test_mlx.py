import quant.amt.compute as c

c._MLX_MIN_SIZE = 0

print("Testing MLX...")
print("Gaussian Weights:", c.batch_gaussian_weights([1.0, 2.0, 3.0], 2.0, 1.0))
print("Weighted Moments:", c.batch_weighted_moments([1.0, 2.0, 3.0], [10.0, 20.0, 10.0]))
print("Linreg Slope:", c.batch_linreg_slope([1.0, 2.0, 3.0]))
print("ATR:", c.batch_atr([10.0, 15.0, 20.0], [5.0, 10.0, 15.0], [8.0, 12.0, 18.0], period=2))
print("MLX OK!")
