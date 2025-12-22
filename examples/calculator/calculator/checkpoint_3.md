# Checkpoint 3 spec:
- Function definition: `def square(x): return x * x`
- Function calls: `square(5)` (should return 25)
- Function with multiple parameters: `def add(a, b): return a + b; add(3, 4)` (should return 7)
- History command: `history` (should show previous calculations)
- Clear command: `clear` (should clear history)
- Exit with code `1` on invalid function definition
- Exit with code `2` on function call errors
- Exit with code `3` otherwise