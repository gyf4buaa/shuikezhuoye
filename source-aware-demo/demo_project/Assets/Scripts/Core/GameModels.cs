// SYNTHETIC DEMO PROJECT - fabricated for a course PoC. Not real game code.
namespace SyntheticNaval.Core
{
    public sealed class PlayerProfile
    {
        public int Rank { get; set; }
        public int FleetCapacity { get; set; }
    }

    public sealed class Reward
    {
        public bool IsRankReward { get; set; }
        public int ItemCount { get; set; }
    }

    public sealed class LeaderboardRow
    {
        public int Position { get; set; }
        public bool Claimed { get; set; }
    }
}
