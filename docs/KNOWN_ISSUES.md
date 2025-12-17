## Solutions

Part of the issue with having solutions is that any errors "underspecifications" from early checkpoints ends up propagating through all future checkpoints. Additionally, given the size of the solutions, debugging them ends up being a major time sink and thus we focused on ensure case correctness rather trying to fix all of the solutions.

* **File Merger:**
    - **Checkpoint 2:** The current solution doesn't solve it, but the tests are correct.
    - **Checkpoint 3:** Same issue as checkpoint 2, plus the empty input case.
* **EVE Market Tools:**
    - **Checkpoint 1/2:** The solution is wrong for a few cases, but the expected answers are correct. Verified them with the market data used in testing.
    - **Checkpoint 3:** The exact yields are usually off by 1 or 2 for the solution, but the verifier calculates what we should see with reprocessing--so the expected cases are correct
* **EVE Industry:** 
    - **Checkpoint 5:** The current solution for checkpoint 5 has the wrong rounding for recursive jobs. Eventually this will be fixed. But the tests are correct
* **Dynamic Buffer:**
    - **Checkpoint 4:** The current solution has incorrect code generation for C++/Rust. The tests are the exact same for all languages, so again good to go -- this will eventually be fixed. 
* **Execution Server:**
    - **Checkpoint 6:** Yes the cases fail for the solution, but the cases have been verified to be the correct behaviors per the specifications.

## CLI

* **results.json** at the file level is redundant/annoying and eventually we will get rid of it.

## Dashboards

* At this point, only bob knows how those dashboards work because i vibed a bit too much on them.

## Agents

* The models/providers/agents are kinda hard to use. I get that. I am very open to it being changed to make it easier to use.

## Results Saving
* The `overall_quality.json` is not well organized currently, going to fix it soon TM.