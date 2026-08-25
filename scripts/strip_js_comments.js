#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
function stripJSComments(code) {
    let output = '';
    let i = 0;
    let inSingleQuote = false;
    let inDoubleQuote = false;
    let inTemplate = false;
    let inRegex = false;
    let inLineComment = false;
    let inBlockComment = false;
    let escapeNext = false;
    while (i < code.length) {
        const ch = code[i];
        const next = code[i + 1];
        if (inLineComment) {
            if (ch === '\n') {
                inLineComment = false;
                output += ch;
            }
            i++;
            continue;
        }
        if (inBlockComment) {
            if (ch === '*' && next === '/') {
                inBlockComment = false;
                i += 2;
            } else {
                if (ch === '\n') output += ch;
                i++;
            }
            continue;
        }
        if (inSingleQuote) {
            output += ch;
            if (ch === '\\') {
                escapeNext = true;
            } else if (ch === "'" && !escapeNext) {
                inSingleQuote = false;
            }
            escapeNext = false;
            i++;
            continue;
        }
        if (inDoubleQuote) {
            output += ch;
            if (ch === '\\') {
                escapeNext = true;
            } else if (ch === '"' && !escapeNext) {
                inDoubleQuote = false;
            }
            escapeNext = false;
            i++;
            continue;
        }
        if (inTemplate) {
            output += ch;
            if (ch === '\\') {
                escapeNext = true;
            } else if (ch === '`' && !escapeNext) {
                inTemplate = false;
            }
            escapeNext = false;
            i++;
            continue;
        }
        if (inRegex) {
            output += ch;
            if (ch === '\\') {
                escapeNext = true;
            } else if (ch === '/' && !escapeNext) {
                inRegex = false;
            }
            escapeNext = false;
            i++;
            continue;
        }
        if (ch === '/' && next === '/') {
            inLineComment = true;
            i += 2;
            continue;
        }
        if (ch === '/' && next === '*') {
            inBlockComment = true;
            i += 2;
            continue;
        }
        if (ch === "'") {
            inSingleQuote = true;
            output += ch;
            i++;
            continue;
        }
        if (ch === '"') {
            inDoubleQuote = true;
            output += ch;
            i++;
            continue;
        }
        if (ch === '`') {
            inTemplate = true;
            output += ch;
            i++;
            continue;
        }
        if (ch === '/' && !inRegex) {
            const prevNonSpace = output.trimEnd().slice(-1);
            const regexContext = ['(', '=', ':', ',', ';', '{', '[', '?', '!', '&', '|', '+', '-', '*', '%', '^', '<', '>', '~', '\n'];
            if (regexContext.includes(prevNonSpace) || output.trimEnd() === '') {
                inRegex = true;
                output += ch;
                i++;
                continue;
            }
        }
        output += ch;
        i++;
    }
    const lines = output.split('\n');
    const cleaned = lines.filter(line => line.trim() !== '').join('\n');
    return cleaned;
}
function processFile(filePath, inPlace = false) {
    const code = fs.readFileSync(filePath, 'utf8');
    const stripped = stripJSComments(code);
    if (inPlace) {
        fs.writeFileSync(filePath, stripped);
        console.log(`Processed: ${filePath}`);
    } else {
        console.log(`=== ${filePath} ===`);
        console.log(stripped);
    }
}
function main() {
    const args = process.argv.slice(2);
    if (args.length === 0) {
        console.log('Usage: node strip_js_comments.js <file_or_directory> [--in-place]');
        process.exit(1);
    }
    const target = args[0];
    const inPlace = args.includes('--in-place');
    const stats = fs.statSync(target);
    let files = [];
    if (stats.isFile()) {
        files = [target];
    } else if (stats.isDirectory()) {
        function walk(dir) {
            const entries = fs.readdirSync(dir, { withFileTypes: true });
            for (const entry of entries) {
                const fullPath = path.join(dir, entry.name);
                if (entry.isDirectory()) {
                    const excludeDirs = ['node_modules', '.git', '.venv', '__pycache__', 'dist', 'build', '.mypy_cache'];
                    if (!excludeDirs.includes(entry.name)) {
                        walk(fullPath);
                    }
                } else if (entry.isFile() && /\.(ts|tsx|js|jsx)$/.test(entry.name)) {
                    files.push(fullPath);
                }
            }
        }
        walk(target);
    }
    for (const f of files) {
        processFile(f, inPlace);
    }
}
main();