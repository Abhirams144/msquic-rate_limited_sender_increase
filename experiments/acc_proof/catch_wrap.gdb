# Catches the AimdAccumulator wrap in unmodified upstream cubic.c.
# Breaks on line 661 (AimdAccumulator -= AimdWindow) only when the subtraction
# is about to go below zero, prints the operands and the uint32 result, the
# calling test, and continues. (No `next` inside the command list: gdb ignores
# the rest of a command list after a command that resumes execution.)
set pagination off
set debuginfod enabled off
set $hits = 0
break cubic.c:661 if Cubic->AimdAccumulator < Cubic->AimdWindow
commands
  silent
  set $hits = $hits + 1
  printf "\n=== underflow %d at cubic.c:661  AimdAccumulator -= AimdWindow ===\n", $hits
  printf "AimdWindow (already grown on line 660) = %u\n", Cubic->AimdWindow
  printf "AimdAccumulator before the subtraction = %u\n", Cubic->AimdAccumulator
  printf "AimdAccumulator after (uint32 result)  = %u\n", (unsigned int)(Cubic->AimdAccumulator - Cubic->AimdWindow)
  printf "CongestionWindow                       = %u\n", Cubic->CongestionWindow
  bt 2
  continue
end
run
printf "\nTotal underflows: %d\n", $hits
quit
