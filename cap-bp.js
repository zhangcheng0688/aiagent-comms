// 直接调 daemon，绕开 MCP 5s 超时
const path = "/Applications/MiniMax Code.app/Contents/Resources/resources/daemon/cli.js";
const { spawn } = require("child_process");

const calls = [
  ["mcp", "call", "playwright", "browser_navigate", '{"url":"http://127.0.0.1:8766/static/business-plan.html"}'],
  ...[1, 3, 6, 9, 12, 15].flatMap(n => {
    const py = (n - 1) * 929;
    return [
      ["mcp", "call", "playwright", "browser_evaluate", JSON.stringify({function: `() => { window.scrollTo(0, ${py}); return ${py}; }`})],
      ["mcp", "call", "playwright", "browser_take_screenshot", JSON.stringify({type: "jpeg", filename: `bpz${n}.jpg`, fullPage: false})],
    ];
  }),
];

async function run() {
  for (const args of calls) {
    const p = spawn("node", [path, ...args], { stdio: ["ignore", "pipe", "pipe"] });
    let out = "", err = "";
    p.stdout.on("data", d => out += d);
    p.stderr.on("data", d => err += d);
    const code = await new Promise(r => p.on("close", r));
    console.log(args.slice(0, 4).join(" "), "→", code, out.slice(-200).replace(/\n/g, " "));
    // 给浏览器渲染时间
    if (args[3] === "browser_navigate") await new Promise(r => setTimeout(r, 8000));
    else if (args[3] === "browser_evaluate") await new Promise(r => setTimeout(r, 3500));
    else await new Promise(r => setTimeout(r, 1500));
  }
}
run();
