import torch
from pathlib import Path
import torchxrayvision as xrv
from models.privacy_model import EnhancedPrivacyXrayModel
from explainer.explainer import PrivacyAwareExplainer


def main():
    # Configuration
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    privacy_config = {
        "privacy_level": 0.1,
        "homomorphic_params": {
            "poly_modulus_degree": 8192,
            "coeff_mod_bit_sizes": [60, 40, 40, 60],
        },
    }

    # Initialize model
    model = EnhancedPrivacyXrayModel(device, privacy_config)
    explainer = PrivacyAwareExplainer(model, device)

    # Load and process image
    image_path = "xray.jpg"
    image = xrv.utils.load_image(image_path)
    image_tensor = torch.from_numpy(image).unsqueeze(0).to(device)

    # Get predictions and explanations
    with torch.no_grad():
        predictions, privacy_metrics = model(image_tensor)

    # Generate explanations
    lime_exp = explainer.generate_lime_explanation(image)
    saliency_map = explainer.generate_saliency_map(image_tensor)

    # Print results
    print("Predictions:", torch.sigmoid(predictions))
    print("Privacy Metrics:", privacy_metrics)

    # Visualize results
    explainer.visualize_explanations(
        image, lime_exp, saliency_map, torch.sigmoid(predictions).cpu().numpy()
    )


if __name__ == "__main__":
    main()
