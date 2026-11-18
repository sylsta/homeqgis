#!/usr/bin/env node
/*
 * Add the DomotiQGIS monitors to Uptime Kuma (2.x), on the Raspberry Pi.
 *
 *   node uptime_kuma_monitors.js
 *
 * - First run of Uptime Kuma (database not chosen yet): chooses SQLite.
 * - No admin account yet: creates it; otherwise logs in.
 * - Asks for the addresses (Enter keeps the default shown, "-" skips a monitor),
 *   then adds the monitors that do not exist yet (same name = skipped, so it can
 *   be run again safely).
 *
 * It uses Uptime Kuma's own Socket.IO API, as its web page does, with the
 * socket.io-client library installed with Uptime Kuma (KUMA_DIR, ~/uptime-kuma
 * by default). Uptime Kuma's address: KUMA_URL (http://127.0.0.1:3001).
 */

"use strict";

const os = require("os");
const path = require("path");
const readline = require("readline");
const { createRequire } = require("module");

const KUMA_URL = process.env.KUMA_URL || "http://127.0.0.1:3001";
const KUMA_DIR = process.env.KUMA_DIR || path.join(os.homedir(), "uptime-kuma");

// Fields the web page sends with every new monitor (Uptime Kuma 2.5, EditMonitor.vue)
const DEFAULTS = {
    type: "http", name: "", parent: null, url: "https://", method: "GET",
    interval: 60, retryInterval: 60, resendInterval: 0, maxretries: 1,
    notificationIDList: {}, ignoreTls: false, upsideDown: false,
    expiryNotification: false, maxredirects: 10, accepted_statuscodes: ["200-299"],
    dns_resolve_type: "A", dns_resolve_server: "", docker_container: "", docker_host: null,
    proxyId: null, basic_auth_user: "", basic_auth_pass: "", authMethod: null,
    httpBodyEncoding: "json", kafkaProducerBrokers: [], kafkaProducerSaslOptions: { mechanism: "None" },
    kafkaProducerSsl: false, kafkaProducerAllowAutoTopicCreation: false, rabbitmqNodes: [],
    conditions: [], timeout: 48, active: true,
};

/** The monitors, from the answers. A monitor whose address is empty is skipped. */
function monitors(a) {
    const list = [];
    if (a.robot) {
        list.push({ name: "Robot (Valetudo)", type: "http", url: `http://${a.robot}` });
        list.push({ name: "Robot SSH", type: "port", hostname: a.robot, port: 22 });
    }
    list.push({ name: "Mosquitto (MQTT)", type: "port", hostname: "127.0.0.1", port: 1883 });
    if (a.ha) {
        list.push({ name: "Home Assistant", type: "http", url: a.ha });
    }
    if (a.nuc) {
        list.push({ name: "NUC", type: "ping", hostname: a.nuc, timeout: 10, ping_count: 1,
                    ping_numeric: true, ping_per_request_timeout: 2 });
        if (a.cockpit) {
            // Cockpit's certificate is self-signed
            list.push({ name: "Cockpit (NUC)", type: "http", url: `https://${a.nuc}:9090`, ignoreTls: true });
        }
    }
    if (a.kodi) {
        // Kodi's web page asks for a password: an open port is the honest check
        const [host, port] = a.kodi.split(":");
        list.push({ name: "Kodi", type: "port", hostname: host, port: Number(port || 8080) });
    }
    return list.map((m) => ({ ...DEFAULTS, ...m }));
}

// -- questions -----------------------------------------------------------------------
// Answers are read line by line (typed, or piped: printf "…\n…" | node …).

function lineReader() {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout,
                                          terminal: Boolean(process.stdin.isTTY) });
    const queue = [];
    const waiting = [];
    let closed = false;
    let hidden = false;
    const write = rl._writeToOutput;
    rl._writeToOutput = function (text) {   // while hidden, the typed characters are not echoed
        if (!hidden) {
            write.call(rl, text);
        }
    };
    rl.on("line", (line) => (waiting.length ? waiting.shift()(line) : queue.push(line)));
    rl.on("close", () => {
        closed = true;
        waiting.splice(0).forEach((resolve) => resolve(null));
    });
    return {
        next(prompt, secret = false) {
            process.stdout.write(prompt);
            hidden = secret && process.stdin.isTTY;
            return new Promise((resolve) => {
                const done = (line) => {
                    if (hidden) {
                        process.stdout.write("\n");
                    }
                    hidden = false;
                    resolve(line);   // null: no more input
                };
                if (queue.length) {
                    done(queue.shift());
                } else if (closed) {
                    done(null);
                } else {
                    waiting.push(done);
                }
            });
        },
        close() { rl.close(); },
    };
}

async function answer(reader, prompt, secret = false) {
    const line = await reader.next(prompt, secret);
    if (line === null) {
        throw new Error("the input ended before every question was answered");
    }
    return line;
}

async function ask(reader, question, fallback = "") {
    const answer_ = (await answer(reader, fallback ? `${question} [${fallback}]: ` : `${question}: `)).trim();
    return answer_ === "-" ? "" : answer_ || fallback;
}

async function askHidden(reader, question) {
    return answer(reader, `${question}: `, true);
}

// -- Uptime Kuma -----------------------------------------------------------------------

async function setupDatabaseIfNeeded() {
    let info;
    try {
        info = await (await fetch(`${KUMA_URL}/setup-database-info`)).json();
    } catch (e) {
        return false;   // main server already running: nothing to choose
    }
    if (!info || !info.needSetup) {
        return false;
    }
    console.log("First run: choosing the SQLite database…");
    const res = await fetch(`${KUMA_URL}/setup-database`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dbConfig: { type: "sqlite" } }),
    });
    if (!res.ok) {
        throw new Error(`database setup refused: ${await res.text()}`);
    }
    return true;
}

function connect(io) {
    return new Promise((resolve, reject) => {
        const socket = io(KUMA_URL, { transports: ["websocket"], reconnection: true,
                                      reconnectionAttempts: 60, reconnectionDelay: 2000 });
        const timer = setTimeout(() => reject(new Error(`no answer from ${KUMA_URL}`)), 150000);
        socket.on("connect", () => { clearTimeout(timer); resolve(socket); });
    });
}

function call(socket, event, ...args) {
    return new Promise((resolve) => socket.emit(event, ...args, resolve));
}

async function main() {
    let io;
    try {
        io = createRequire(path.join(KUMA_DIR, "package.json"))("socket.io-client").io;
    } catch (e) {
        throw new Error(`socket.io-client not found in ${KUMA_DIR} (set KUMA_DIR to Uptime Kuma's folder)`);
    }
    const rl = lineReader();
    try {
        console.log("Addresses: Enter keeps the value in brackets, \"-\" skips the monitor.");
        const answers = {
            robot: await ask(rl, "Robot (Valetudo) IP", "192.168.50.20"),
            ha: await ask(rl, "Home Assistant address (e.g. http://192.168.50.2:8123)"),
            nuc: await ask(rl, "NUC IP"),
        };
        answers.cockpit = answers.nuc
            && (await ask(rl, "Cockpit on the NUC (port 9090)? y/n", "y")).toLowerCase().startsWith("y");
        answers.kodi = await ask(rl, "Kodi (IP:port)", answers.nuc ? `${answers.nuc}:8080` : "");
        const list = monitors(answers);

        const freshDatabase = await setupDatabaseIfNeeded();
        if (freshDatabase) {
            console.log("Waiting for Uptime Kuma to start (a minute or two on a Pi)…");
        }
        const socket = await connect(io);
        const username = await ask(rl, "Uptime Kuma username", "admin");
        const password = await askHidden(rl, "Uptime Kuma password");

        if (await call(socket, "needSetup")) {
            console.log(`Creating the admin account "${username}"…`);
            const created = await call(socket, "setup", username, password);
            if (!created.ok) {
                throw new Error(`account not created: ${created.msg}`);
            }
        }
        const existing = new Set();
        socket.on("monitorList", (monitorsById) => {
            for (const m of Object.values(monitorsById || {})) {
                existing.add(m.name);
            }
        });
        let login = await call(socket, "login", { username, password, token: "" });
        if (login.tokenRequired) {
            const token = await ask(rl, "Two-factor code");
            login = await call(socket, "login", { username, password, token });
        }
        if (!login.ok) {
            throw new Error(`login refused: ${login.msg}`);
        }

        let added = 0;
        for (const monitor of list) {
            if (existing.has(monitor.name)) {
                console.log(`= ${monitor.name}: already there`);
                continue;
            }
            const result = await call(socket, "add", monitor);
            if (result.ok) {
                added += 1;
                console.log(`+ ${monitor.name}`);
            } else {
                console.log(`! ${monitor.name}: ${result.msg}`);
            }
        }
        console.log(`${added} monitor(s) added. Uptime Kuma: ${KUMA_URL.replace("127.0.0.1", "<Pi IP>")}`);
        socket.close();
    } finally {
        rl.close();
    }
}

if (require.main === module) {
    main().catch((e) => {
        console.error(`Error: ${e.message}`);
        process.exit(1);
    });
}

module.exports = { monitors, DEFAULTS };
