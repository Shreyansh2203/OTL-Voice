import { describe, it, expect } from 'vitest';
import { extractEntries, stripEntriesBlock } from './entries';

describe('entries utils', () => {
  describe('extractEntries', () => {
    it('should extract valid JSON entries from a code block', () => {
      const text = `Here is your summary:
\`\`\`json
{
  "entries": [
    { "projectNo": 1234, "hours": 5 }
  ]
}
\`\`\`
`;
      const entries = extractEntries(text);
      expect(entries).toEqual([{ projectNo: 1234, hours: 5 }]);
    });

    it('should return null if no code block exists', () => {
      const entries = extractEntries("No json here!");
      expect(entries).toBeNull();
    });

    it('should return null if JSON is invalid', () => {
      const text = `\`\`\`json\n{ "entries": [\n\`\`\``;
      const entries = extractEntries(text);
      expect(entries).toBeNull();
    });

    it('should return null if JSON does not contain valid entries array', () => {
      const text1 = `\`\`\`json\n{ "entries": [] }\n\`\`\``;
      expect(extractEntries(text1)).toBeNull();

      const text2 = `\`\`\`json\n{ "notEntries": 123 }\n\`\`\``;
      expect(extractEntries(text2)).toBeNull();
    });
  });

  describe('stripEntriesBlock', () => {
    it('should strip the markdown code block and everything after', () => {
      const text = "Message text\n```json\n{...}\n```";
      expect(stripEntriesBlock(text)).toBe("Message text");
    });

    it('should return the original text if no block exists', () => {
      expect(stripEntriesBlock("Just text")).toBe("Just text");
    });
  });
});
