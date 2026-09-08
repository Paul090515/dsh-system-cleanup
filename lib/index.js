/**
 * dsh-system-cleanup — DSH skill plugin.
 *
 * Bundles the `system-cleanup` skill (SKILL.md + scripts + references) as a
 * runtime skill contribution via `ctx.skills.register(...)`. The skill's body
 * uses relative paths (e.g. `scripts/cleanup.sh`), resolved against this
 * package directory through `resourceBase`.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'dsh-system-cleanup';
export const inject = ['skills'];

const here = dirname(fileURLToPath(import.meta.url));
const packageDir = join(here, '..');

const { meta, body } = parseSkillMarkdown(readFileSync(join(packageDir, 'SKILL.md'), 'utf8'));

export function apply(ctx) {
  ctx.skills.register({
    name: meta.name || 'system-cleanup',
    description: meta.description || '',
    whenToUse: meta.whenToUse || undefined,
    source: 'bundled',
    resourceBase: { kind: 'directory', path: packageDir },
    content: body,
  });
}

/**
 * Minimal frontmatter parser for the top-level scalar fields this skill uses
 * (name / description / whenToUse). Nested blocks (e.g. `metadata:`) are
 * intentionally ignored; the body is everything after the closing `---`.
 */
function parseSkillMarkdown(md) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(md);
  if (!m) return { meta: {}, body: md };
  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (kv) meta[kv[1]] = kv[2].trim();
  }
  return { meta, body: md.slice(m[0].length) };
}
