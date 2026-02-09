--[[
  TIO Lua Script: Run MagTag Benchmarks
  =====================================
  Automates running the full benchmark suite via serial.

  Usage:
    tio /dev/cu.usbmodem* --script-file scripts/run_benchmarks.lua \
        --log --log-file logs/bench_$(date +%Y%m%d_%H%M%S).log

  Or with no-reconnect to exit when done:
    tio /dev/cu.usbmodem* --script-file scripts/run_benchmarks.lua \
        --log --log-file logs/bench_$(date +%Y%m%d_%H%M%S).log \
        --no-reconnect
]]--

print("[tio] MagTag Benchmark Runner")
print("[tio] Sending soft reboot (Ctrl+C, Ctrl+D)...")

-- Interrupt any running code
write("\x03")  -- Ctrl+C
msleep(200)

-- Soft reboot to run main.py
write("\x04")  -- Ctrl+D
msleep(500)

-- Wait for the benchmark to start booting
print("[tio] Waiting for boot sequence...")
local result = expect("BOOT BENCHMARKS", 10000)
if result ~= 1 then
    print("[tio] ERROR: Boot sequence not detected, timeout")
    exit(1)
end

-- Wait for hardware init to complete and menu to be ready
print("[tio] Boot detected, waiting for menu...")
result = expect("Free RAM ready for menu", 30000)
if result ~= 1 then
    print("[tio] ERROR: Menu not ready, timeout")
    exit(1)
end

-- Small delay to ensure menu is fully drawn
msleep(500)

-- Send 'r' to trigger headless "Run All" mode
print("[tio] Triggering Run All benchmarks...")
write("r")

-- Wait for benchmark completion
print("[tio] Running benchmarks, waiting for completion...")
result = expect("Benchmark Complete", 300000)  -- 5 minute timeout
if result == 1 then
    print("[tio] Benchmarks completed successfully!")
else
    print("[tio] WARNING: Completion message not detected (timeout or error)")
end

-- Give time for final output to flush
msleep(1000)
print("[tio] Done. Check log file for results.")

-- Exit tio cleanly using the Lua API
exit(0)
