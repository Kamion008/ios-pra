# The generator-base correction, reproduced:
# diff -rq work/ci181/post0179/xnu work/ci181/post0180/xnu
# (post0179 = run 44358321437's xnu-buildtree artifact; post0180 = run
#  44362560978's - the flashed boot-T4 kernel's source)

  Files work/ci181/post0179/xnu/bsd/dev/pra_touch.c and work/ci181/post0180/xnu/bsd/dev/pra_touch.c differ

-> bsd/dev/pra_touch.c is the ONLY differing file: 0180 modified it, so
-> 0181 (also touching pra_touch.c) must be generated from the post-0180
-> tree and applies onto the stack AFTER 0180. The brief's 44358321437
-> (post-0179) would generate hunks against a file state that no longer
-> exists in the stack.
