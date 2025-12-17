const { DynamicPreprocessor } = require("./dynamic_js_buffer");
const { argv } = require("node:process");

// Very lightweight arg parsing (similar to argparse defaults)
function parseArgs() {
  const args = {
    data_file: null,
    buffer: 1024,
    cache_dir: null,
  };

  const positional = [];

  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--buffer=")) {
      args.buffer = parseInt(a.split("=")[1], 10);
    } else if (a === "--buffer") {
      args.buffer = parseInt(argv[++i], 10);
    } else if (a.startsWith("--cache_dir=")) {
      args.cache_dir = a.split("=")[1];
    } else if (a === "--cache_dir") {
      args.cache_dir = argv[++i];
    } else {
      // Assume positional
      positional.push(a);
    }
  }

  if (positional.length < 1) {
    console.error("Usage: node script.js <data_file> [--buffer N] [--cache_dir PATH]");
    process.exit(1);
  }

  args.data_file = positional[0];
  return args;
}

const args = parseArgs();

// Construct JS analogue of DynamicPreprocessor
const preprocessor = new DynamicPreprocessor({
  buffer: args.buffer,
  cacheDir: args.cache_dir,
});

console.log("---\nSTARTING\n---");

// Assuming `preprocessor(file)` returns an async iterable or iterable of rows
for (const row of preprocessor.process(args.data_file)) {
  console.log(JSON.stringify(row));
}