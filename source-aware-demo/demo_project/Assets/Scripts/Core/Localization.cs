// SYNTHETIC DEMO PROJECT - fabricated for a course PoC. Not real game code.
using System.Collections.Generic;

namespace SyntheticNaval.Core
{
    public static class L
    {
        private static readonly Dictionary<string, string> Strings = new Dictionary<string, string>();

        public static string Get(string key)
        {
            return Strings.TryGetValue(key, out var value) ? value : key;
        }

        public static void Load(IReadOnlyDictionary<string, string> table)
        {
            Strings.Clear();
            foreach (var pair in table)
            {
                Strings[pair.Key] = pair.Value;
            }
        }
    }
}
