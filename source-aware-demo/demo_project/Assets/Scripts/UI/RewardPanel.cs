// SYNTHETIC DEMO PROJECT - fabricated for a course PoC. Not real game code.
using SyntheticNaval.Core;
using UnityEngine;
using UnityEngine.UI;

namespace SyntheticNaval.UI
{
    public sealed class RewardPanel : MonoBehaviour
    {
        [SerializeField] private Text titleLabel;
        [SerializeField] private Text claimButtonLabel;
        [SerializeField] private Button claimButton;
        [SerializeField] private Button claimAllButton;

        private void Awake()
        {
            claimButton.onClick.AddListener(OnClaim);
            claimAllButton.onClick.AddListener(OnClaimAll);
        }

        public void Show(Reward reward)
        {
            // Victory reward pop-up: claiming grants the items listed below.
            titleLabel.text = L.Get("ui.reward.title");
            claimButtonLabel.text = L.Get("ui.reward.claim");
            claimAllButton.GetComponentInChildren<Text>().text = L.Get("ui.reward.claim_all");
        }

        private void OnClaim()
        {
            // Disable immediately; the real label comes from the string table.
            claimButtonLabel.text = "Claim";
            claimButton.interactable = false;
        }

        private void OnClaimAll()
        {
            claimButtonLabel.text = L.Get("ui.reward.claim_all");
        }
    }
}
