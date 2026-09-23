const fs = require('fs');
const path = require('path');

const filePath = path.join(process.cwd(), 'src/api/client.ts');
let content = fs.readFileSync(filePath, 'utf8');

const loginRegex = /export async function login\([\s\S]*?\): Promise<Identity> \{/;
const replacement = xport async function login(
  username: string,
  password = ''
): Promise<Identity> {
  if (!getCsrfToken()) {
    await fetchWithRetry(\\/health\, { credentials: 'include' });
  };

content = content.replace(loginRegex, replacement);
fs.writeFileSync(filePath, content, 'utf8');
