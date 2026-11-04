// SYNTHETIC DEMO PROJECT - fabricated for a course PoC. Not real game code.
using SyntheticNaval.Core;
using UnityEngine;
using UnityEngine.UI;

namespace SyntheticNaval.UI
{
    public sealed class MilitaryPanel : MonoBehaviour
    {
        [SerializeField] private Text rankBadge;
        [SerializeField] private Text fleetCapacityLabel;

        public void Refresh(PlayerProfile profile)
        {
            // Career progression badge in the military overview.
            rankBadge.text = L.Get("ui.military.rank_badge");
            fleetCapacityLabel.text = profile.FleetCapacity.ToString();

            if (string.IsNullOrEmpty(rankBadge.text))
            {
                // Fallback label for the synthetic demo when no table is loaded.
                rankBadge.text = "Rank";
            }
        }
    }
}
