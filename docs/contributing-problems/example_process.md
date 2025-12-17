# Example: Designing a Calculator Problem

This walkthrough shows the design thinking process for creating a multi-checkpoint problem.

> **Reading path:** [Design Philosophy](README.md) → **You are here** → [Implementation Tutorial](../problems/tutorial.md) → [Checklist](checklist.md)

---

## The Design Process

Imagine we want to add a problem where the goal is to build a calculator CLI application that stores history and supports advanced operations. Our guiding question is: **"What does the *final* program do?"**

* Considering this first allows us to have a high-level understanding of what our checkpoints will look like.  
  * Makes checkpoints more focused and easier to write  
* Writing the first checkpoint becomes so much easier if you know what the overarching goal looks like

What is our core problem then? A calculator CLI that:

* Supports a DSL for simple functions, calculus, linear algebra, and linear programming  
* Evaluates parsed expressions  
* Saves the history to the disk and allows resumption from it  
* Supports a limited set of commands for modifying the history  
* Supports user-defined functions/variables

Next what do the **good/bad** solutions look like:

* **Bad:**  
  * Performs string replacement to then exploit a language interpreter (e.g. python's `eval` function)  
  * Doesnt have any simplification logic  
  * Keeps a running list of just strings/output values  
  * Massive if conditionals for commands  
* **Good:**  
  * Defines a main loop that handles the parsing  
  * Parses expressions into a tree  
  * Has an abstraction for functions/primitives/commands  
  * Uses inheritance/some similar method to group related functions/operations together  
  * Simplifies the parsed trees before evaluating them  
* From this, our rough set of checkpoints would be:  
  * **Checkpoint 1:** Write an calculator CLI program that supports primitive/trig/logarithmic operations, basic constants, and history.  
  * **Checkpoint 2:** Add in support for user defined functions and variables  
  * **Checkpoint 3:** Add in support for derivatives and integrals.  
  * **Checkpoint 4:** Add in vectors, matrices, and linear algebra operations.  
  * **Checkpoint 5:** Add in linear programming and optimization..  
* The core problem is outlined in the first checkpoint --> A calculator that evaluates string expressions with a history  
  * No Checkpoints are destructive to this  
* Immediately, there is a clear underlying structure:  
  * Parse + Validate input (e.g. `ln(2 - ln(e^$1))` --> `LN(SUB(2,LN(POW($E,$LAST_VALUE))))`)  
  * Create Execution plan (e.g. `POW($E,$LAST_VALUE)`,`LN($RESULT)`,`SUB(2,$RESULT)`, `LN($RESULT)`)  
  * Evaluate the expression and handle errors gracefully (e.g. `$LAST_VALUE=0`=> `1`, if `$LAST_VALUE=2`=> domain error)  
  * Update the history

## Example Calculator Checkpoint 1
```
Write `%%%ENTRYPOINT:entry_file%%%` CLI application that evaluates expressions from the STDIN. It needs to support history tracking through vim like commands.

# Deliverable

\```
%%%ENTRYPOINT:entry_command%%% --history <Path to the history JSONL file> [--overwrite]
\```

* `--history`: points to the file (if not exist, make it) where the history of the calculator should be saved.
* `--overwrite`: Whether to start the calculator from an empty history. 
## Supported Functions
* Basic primitive math operations `()*/+-^%` and trig functions.
* Logarithmic functions: `log2`,`log10`, `ln`, and `log({x}, {base})`.
* Constants: `pi` and `e`
* `${N}` -> uses the value at the n'th previous value in the history. 1-indexed

## Commands
Commands are prefix'ed with `:`. The commands you must support:
* `undo`/`redo` -- Undoes/redoes the last operation * `clear` -- clears the history.
* `decimals` -- Sets the number of decimal points to print. Default is 2.

## Error Handling
Support the following error types printed to STDERR:
* `Syntax Error: <message>`
* `Unknown Symbol: '<symbol name>'`
* `Domain Error: <message>`: Includes zero division as well. 
# Example
`>>>` indicates user STDIN input.
\```
>>> 1-1
0
>>> 1 / (2-2)
Domain Error: ...
>>> ln(2 - e^$1)
0
>>> log2(4)
2
>>> e^$1
7.39
>>> ln(2 - ln(e^$2))
Domain Error: ...
>>> :undo
>>> :undo
>>> ln(2 - ln(e^$2))
0.69
>>> Abc
Unknown Symbol: Abc
>>> x +
Syntax Error: ...
\```
```
* **Notes:**  
  * Clearly defines the exact entrypoint script we want.  
  * Defined the exact set of functions we will test on when they are ambiguous.  
    * For trig functions, it is straightforward what is expected  
    * For logarithmic, we define the exact syntax we want because it otherwise could be an arbitrary decision that does not affect the core problem  
    * Same for the history operations -- we give the commands we want because otherwise it becomes arbitrary what is selected to represent the same core functionality.  
  * Examples are WAY more informative then text -- they give the implied behaviors that otherwise we would need to detail.  
  * We dont provide the examples of what we are expecting to be saved in the history file nor the `--overwrite` behavior.  
    * The overwrite should be self explanatory.  
    * The underlying representation of the history is not important to us -- We can test its functionality without checking it exactly

## Example Calculator Checkpoint 2


```
Extend the CLI calculator to now support user defined functions and variables.

# Deliverables

The syntax for defining a function/variable is: 
\```
let <variable> <- <value>
let <function>: <arg1>,<arg2>,...,<argn> -> <expression>
\```
Symbols can be any combination of alphanumeric characters with `_` allowed.


Add in support for inline if conditionals with the syntax: `<predicate>? <value if true>:<value if false>`. Add support for primitive conditionals, `&`, and `|`.
**Notes:**
* Symbols can be overridden and there is basic scoping associated with them. They can also override builtin functions.
* Recursion is also allowed.

## Commands

Add in the new command `symbols` that prints the user defined symbols in lexographical order.

# Examples

`>>>` indicates user STDIN input. 
\```
>>> let x <- 10
x = 10
>>> let f: x,y -> x + y
f(x,y) -> x + y
>>> :symbols
f(x,y) -> x + y
x = 10
>>> f(x, 1)
11
>>> f(5,1)
6
>>> f(2)
Domain Error: ...
>>> let f:y-> y>0?f(y-1) + y:y
f(y) -> y > 0 ? f(y-1) + y : y
>>> let x <- 3
x = 3
>>> f(x)
6
>>> :undo
>>> :undo
>>> :undo
>>> f(5,1)
6
\`\`\`
```

---

## Next Steps

Now that you've seen the design process:

1. **[Implement your problem](../problems/tutorial.md)** - Step-by-step tutorial to turn your design into code
2. **[Structure reference](../problems/structure.md)** - Directory layout and file roles
3. **[Validation checklist](checklist.md)** - Pre-submission checklist