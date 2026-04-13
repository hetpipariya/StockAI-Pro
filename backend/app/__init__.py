"""StockAI Pro backend package initialization."""

from __future__ import annotations

import warnings


def _suppress_noisy_model_warnings() -> None:
	# Model artifacts may be trained with an older sklearn minor version.
	# Keep startup logs clean unless model loading genuinely fails.
	try:
		from sklearn.exceptions import InconsistentVersionWarning

		warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
	except Exception:
		warnings.filterwarnings(
			"ignore",
			message=r"Trying to unpickle estimator .* from version .* when using version .*",
			category=UserWarning,
		)


_suppress_noisy_model_warnings()
