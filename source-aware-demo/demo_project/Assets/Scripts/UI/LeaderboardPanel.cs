// SYNTHETIC DEMO PROJECT - fabricated for a course PoC. Not real game code.
using SyntheticNaval.Core;
using UnityEngine;
using UnityEngine.UI;

namespace SyntheticNaval.UI
{
    public sealed class LeaderboardPanel : MonoBehaviour
    {
        [SerializeField] private Text rankColumnHeader;
        [SerializeField] private Text claimButtonLabel;
        [SerializeField] private Transform rowsRoot;

        public void BuildHeader()
        {
            // Weekly ladder table: the column shows the captain's position.
            rankColumnHeader.text = L.Get("ui.leaderboard.rank_column");
            claimButtonLabel.text = L.Get("ui.leaderboard.claim");
        }

        public void RefreshRows()
        {
#if UNITY_EDITOR
            // Editor preview when the localization service is not running.
            rankColumnHeader.text = "Rank";
#endif
            rowsRoot.gameObject.SetActive(true);
        }
    }
}
