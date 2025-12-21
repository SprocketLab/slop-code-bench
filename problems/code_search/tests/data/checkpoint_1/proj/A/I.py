#!/usr/bin/env python3
"""
Machine Learning utilities module for data preprocessing, model training,
and evaluation. Includes implementations of common algorithms and utilities.
"""

import logging
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Container for model evaluation metrics."""

    accuracy: float
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: list[list[int]]
    training_time: float
    prediction_time: float


class DataPreprocessor:
    """Utilities for preprocessing machine learning data."""

    def __init__(self):
        self.scalers = {}
        self.encoders = {}
        self.feature_names = []

    def normalize_features(
        self, X: np.ndarray, method: str = "minmax"
    ) -> np.ndarray:
        """
        Normalize features using specified method.

        Args:
            X: Input feature matrix
            method: Normalization method ('minmax', 'zscore', 'robust')

        Returns:
            Normalized feature matrix
        """
        if method == "minmax":
            X_min = X.min(axis=0)
            X_max = X.max(axis=0)
            X_range = X_max - X_min
            X_range[X_range == 0] = 1  # Avoid division by zero
            X_normalized = (X - X_min) / X_range
            self.scalers["minmax"] = {"min": X_min, "max": X_max}

        elif method == "zscore":
            X_mean = X.mean(axis=0)
            X_std = X.std(axis=0)
            X_std[X_std == 0] = 1  # Avoid division by zero
            X_normalized = (X - X_mean) / X_std
            self.scalers["zscore"] = {"mean": X_mean, "std": X_std}

        elif method == "robust":
            X_median = np.median(X, axis=0)
            X_mad = np.median(np.abs(X - X_median), axis=0)
            X_mad[X_mad == 0] = 1  # Avoid division by zero
            X_normalized = (X - X_median) / X_mad
            self.scalers["robust"] = {"median": X_median, "mad": X_mad}

        else:
            raise ValueError(f"Unknown normalization method: {method}")

        return X_normalized

    def handle_missing_values(
        self, X: np.ndarray, strategy: str = "mean"
    ) -> np.ndarray:
        """
        Handle missing values in the dataset.

        Args:
            X: Input feature matrix
            strategy: Strategy for handling missing values ('mean', 'median', 'mode', 'drop')

        Returns:
            Feature matrix with missing values handled
        """
        if strategy == "drop":
            # Remove rows with missing values
            return X[~np.isnan(X).any(axis=1)]

        if strategy in ["mean", "median"]:
            # Fill with mean or median
            if strategy == "mean":
                fill_values = np.nanmean(X, axis=0)
            else:
                fill_values = np.nanmedian(X, axis=0)

            # Create a mask for missing values
            mask = np.isnan(X)
            X_filled = X.copy()
            X_filled[mask] = np.take(fill_values, np.where(mask)[1])
            return X_filled

        if strategy == "mode":
            # Fill with mode (most frequent value)
            X_filled = X.copy()
            for col in range(X.shape[1]):
                col_data = X[:, col]
                mask = np.isnan(col_data)
                if mask.any():
                    # Calculate mode for non-missing values
                    unique_vals, counts = np.unique(
                        col_data[~mask], return_counts=True
                    )
                    mode_val = unique_vals[np.argmax(counts)]
                    X_filled[mask, col] = mode_val
            return X_filled

        raise ValueError(f"Unknown missing value strategy: {strategy}")

    def feature_selection(
        self,
        X: np.ndarray,
        y: np.ndarray,
        method: str = "correlation",
        k: int = 10,
    ) -> tuple[np.ndarray, list[int]]:
        """
        Select top k features based on specified method.

        Args:
            X: Input feature matrix
            y: Target vector
            method: Feature selection method ('correlation', 'variance', 'mutual_info')
            k: Number of features to select

        Returns:
            Tuple of (selected features, selected feature indices)
        """
        if method == "correlation":
            # Calculate correlation with target
            correlations = np.array(
                [np.corrcoef(X[:, i], y)[0, 1] for i in range(X.shape[1])]
            )
            correlations = np.abs(correlations)  # Use absolute correlation
            top_indices = np.argsort(correlations)[-k:][::-1]

        elif method == "variance":
            # Select features with highest variance
            variances = np.var(X, axis=0)
            top_indices = np.argsort(variances)[-k:][::-1]

        elif method == "mutual_info":
            # Simplified mutual information calculation
            mi_scores = []
            for i in range(X.shape[1]):
                # Discretize continuous variables for MI calculation
                x_discrete = pd.qcut(
                    X[:, i], q=10, labels=False, duplicates="drop"
                )
                y_discrete = pd.qcut(y, q=10, labels=False, duplicates="drop")

                # Calculate mutual information
                mi = self._calculate_mutual_info(x_discrete, y_discrete)
                mi_scores.append(mi)

            top_indices = np.argsort(mi_scores)[-k:][::-1]

        else:
            raise ValueError(f"Unknown feature selection method: {method}")

        return X[:, top_indices], top_indices.tolist()

    def _calculate_mutual_info(self, x: np.ndarray, y: np.ndarray) -> float:
        """Calculate mutual information between two discrete variables."""
        # Create contingency table
        joint_counts = np.zeros((len(np.unique(x)), len(np.unique(y))))

        for i, xi in enumerate(np.unique(x)):
            for j, yj in enumerate(np.unique(y)):
                joint_counts[i, j] = np.sum((x == xi) & (y == yj))

        # Calculate probabilities
        p_xy = joint_counts / len(x)
        p_x = np.sum(p_xy, axis=1, keepdims=True)
        p_y = np.sum(p_xy, axis=0, keepdims=True)

        # Calculate mutual information
        mi = np.sum(p_xy * np.log(p_xy / (p_x * p_y + 1e-10) + 1e-10))

        return mi


class BaseClassifier(ABC):
    """Abstract base class for classifiers."""

    def __init__(self):
        self.is_fitted = False
        self.classes_ = None

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaseClassifier":
        """Fit the classifier to training data."""
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions on new data."""
        pass

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict class probabilities (if supported)."""
        raise NotImplementedError("Probability prediction not supported")


class KNearestNeighbors(BaseClassifier):
    """K-Nearest Neighbors classifier implementation."""

    def __init__(self, k: int = 5, distance_metric: str = "euclidean"):
        """
        Initialize KNN classifier.

        Args:
            k: Number of neighbors to consider
            distance_metric: Distance metric ('euclidean', 'manhattan', 'cosine')
        """
        super().__init__()
        self.k = k
        self.distance_metric = distance_metric
        self.X_train = None
        self.y_train = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "KNearestNeighbors":
        """Fit the KNN classifier."""
        self.X_train = X
        self.y_train = y
        self.classes_ = np.unique(y)
        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions using KNN."""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")

        predictions = []
        for x in X:
            # Calculate distances to all training points
            distances = self._calculate_distances(x)

            # Get indices of k nearest neighbors
            k_indices = np.argsort(distances)[: self.k]

            # Get labels of k nearest neighbors
            k_labels = self.y_train[k_indices]

            # Majority vote
            unique_labels, counts = np.unique(k_labels, return_counts=True)
            prediction = unique_labels[np.argmax(counts)]
            predictions.append(prediction)

        return np.array(predictions)

    def _calculate_distances(self, x: np.ndarray) -> np.ndarray:
        """Calculate distances from x to all training points."""
        if self.distance_metric == "euclidean":
            return np.sqrt(np.sum((self.X_train - x) ** 2, axis=1))
        if self.distance_metric == "manhattan":
            return np.sum(np.abs(self.X_train - x), axis=1)
        if self.distance_metric == "cosine":
            dot_product = np.dot(self.X_train, x)
            norm_x = np.linalg.norm(x)
            norm_train = np.linalg.norm(self.X_train, axis=1)
            return 1 - dot_product / (norm_x * norm_train + 1e-10)
        raise ValueError(f"Unknown distance metric: {self.distance_metric}")


class NaiveBayes(BaseClassifier):
    """Gaussian Naive Bayes classifier implementation."""

    def __init__(self, smoothing: float = 1e-9):
        """
        Initialize Naive Bayes classifier.

        Args:
            smoothing: Laplace smoothing parameter
        """
        super().__init__()
        self.smoothing = smoothing
        self.class_priors = {}
        self.class_means = {}
        self.class_vars = {}

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NaiveBayes":
        """Fit the Naive Bayes classifier."""
        self.classes_ = np.unique(y)
        n_samples, n_features = X.shape

        # Calculate class priors
        for cls in self.classes_:
            class_mask = y == cls
            n_class = np.sum(class_mask)
            self.class_priors[cls] = (n_class + self.smoothing) / (
                n_samples + len(self.classes_) * self.smoothing
            )

            # Calculate class-specific means and variances
            X_class = X[class_mask]
            self.class_means[cls] = np.mean(X_class, axis=0)
            self.class_vars[cls] = np.var(X_class, axis=0) + self.smoothing

        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions using Naive Bayes."""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")

        predictions = []
        for x in X:
            class_scores = {}

            for cls in self.classes_:
                # Calculate log probability for this class
                log_prob = np.log(self.class_priors[cls])

                # Add log likelihood for each feature
                for i in range(len(x)):
                    mean = self.class_means[cls][i]
                    var = self.class_vars[cls][i]

                    # Gaussian probability density
                    log_likelihood = (
                        -0.5 * np.log(2 * np.pi * var)
                        - 0.5 * ((x[i] - mean) ** 2) / var
                    )
                    log_prob += log_likelihood

                class_scores[cls] = log_prob

            # Predict class with highest log probability
            prediction = max(class_scores, key=class_scores.get)
            predictions.append(prediction)

        return np.array(predictions)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict class probabilities."""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")

        probabilities = []
        for x in X:
            class_scores = {}

            for cls in self.classes_:
                log_prob = np.log(self.class_priors[cls])

                for i in range(len(x)):
                    mean = self.class_means[cls][i]
                    var = self.class_vars[cls][i]
                    log_likelihood = (
                        -0.5 * np.log(2 * np.pi * var)
                        - 0.5 * ((x[i] - mean) ** 2) / var
                    )
                    log_prob += log_likelihood

                class_scores[cls] = log_prob

            # Convert log probabilities to probabilities
            max_log = max(class_scores.values())
            exp_scores = {
                cls: np.exp(score - max_log)
                for cls, score in class_scores.items()
            }
            sum_exp = sum(exp_scores.values())

            probas = [exp_scores.get(cls, 0) / sum_exp for cls in self.classes_]
            probabilities.append(probas)

        return np.array(probabilities)


class ModelEvaluator:
    """Utilities for evaluating machine learning models."""

    @staticmethod
    def calculate_metrics(
        y_true: np.ndarray, y_pred: np.ndarray
    ) -> ModelMetrics:
        """
        Calculate comprehensive evaluation metrics.

        Args:
            y_true: True labels
            y_pred: Predicted labels

        Returns:
            ModelMetrics object with all metrics
        """
        # Calculate confusion matrix
        classes = np.unique(np.concatenate([y_true, y_pred]))
        n_classes = len(classes)
        confusion_matrix = np.zeros((n_classes, n_classes), dtype=int)

        for i, cls_true in enumerate(classes):
            for j, cls_pred in enumerate(classes):
                confusion_matrix[i, j] = np.sum(
                    (y_true == cls_true) & (y_pred == cls_pred)
                )

        # Calculate basic metrics
        accuracy = np.mean(y_true == y_pred)

        # Calculate precision, recall, F1 for each class
        precisions = []
        recalls = []
        f1_scores = []

        for i, cls in enumerate(classes):
            tp = confusion_matrix[i, i]
            fp = np.sum(confusion_matrix[:, i]) - tp
            fn = np.sum(confusion_matrix[i, :]) - tp

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0
            )

            precisions.append(precision)
            recalls.append(recall)
            f1_scores.append(f1)

        # Average metrics (macro)
        avg_precision = np.mean(precisions)
        avg_recall = np.mean(recalls)
        avg_f1 = np.mean(f1_scores)

        return ModelMetrics(
            accuracy=accuracy,
            precision=avg_precision,
            recall=avg_recall,
            f1_score=avg_f1,
            confusion_matrix=confusion_matrix.tolist(),
            training_time=0.0,  # To be set by caller
            prediction_time=0.0,  # To be set by caller
        )

    @staticmethod
    def cross_validate(
        model: BaseClassifier, X: np.ndarray, y: np.ndarray, cv_folds: int = 5
    ) -> dict[str, list[float]]:
        """
        Perform cross-validation on the model.

        Args:
            model: Model to evaluate
            X: Feature matrix
            y: Target vector
            cv_folds: Number of cross-validation folds

        Returns:
            Dictionary with metric scores for each fold
        """
        n_samples = len(X)
        fold_size = n_samples // cv_folds

        scores = {"accuracy": [], "precision": [], "recall": [], "f1_score": []}

        # Create cross-validation splits
        indices = np.random.permutation(n_samples)

        for fold in range(cv_folds):
            # Split data
            start_idx = fold * fold_size
            end_idx = (
                start_idx + fold_size if fold < cv_folds - 1 else n_samples
            )

            test_indices = indices[start_idx:end_idx]
            train_indices = np.concatenate(
                [indices[:start_idx], indices[end_idx:]]
            )

            X_train, X_test = X[train_indices], X[test_indices]
            y_train, y_test = y[train_indices], y[test_indices]

            # Train and evaluate
            model_copy = (
                type(model)(**model.__dict__)
                if hasattr(model, "__dict__")
                else model
            )
            model_copy.fit(X_train, y_train)
            y_pred = model_copy.predict(X_test)

            metrics = ModelEvaluator.calculate_metrics(y_test, y_pred)

            scores["accuracy"].append(metrics.accuracy)
            scores["precision"].append(metrics.precision)
            scores["recall"].append(metrics.recall)
            scores["f1_score"].append(metrics.f1_score)

        return scores


def main():
    """Example usage of the ML utilities."""
    # Generate sample data
    np.random.seed(42)
    n_samples = 1000
    n_features = 20

    X = np.random.randn(n_samples, n_features)
    y = (X[:, 0] + X[:, 1] > 0).astype(int)

    # Preprocess data
    preprocessor = DataPreprocessor()
    X_normalized = preprocessor.normalize_features(X, method="zscore")

    # Feature selection
    X_selected, selected_indices = preprocessor.feature_selection(
        X_normalized, y, method="correlation", k=10
    )

    print(f"Selected feature indices: {selected_indices}")
    print(f"Original shape: {X.shape}, Selected shape: {X_selected.shape}")

    # Split data
    split_idx = int(0.8 * len(X_selected))
    X_train, X_test = X_selected[:split_idx], X_selected[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # Train and evaluate KNN
    knn = KNearestNeighbors(k=5)
    knn.fit(X_train, y_train)
    y_pred_knn = knn.predict(X_test)
    metrics_knn = ModelEvaluator.calculate_metrics(y_test, y_pred_knn)

    print(f"KNN Accuracy: {metrics_knn.accuracy:.3f}")
    print(f"KNN F1 Score: {metrics_knn.f1_score:.3f}")

    # Train and evaluate Naive Bayes
    nb = NaiveBayes()
    nb.fit(X_train, y_train)
    y_pred_nb = nb.predict(X_test)
    metrics_nb = ModelEvaluator.calculate_metrics(y_test, y_pred_nb)

    print(f"Naive Bayes Accuracy: {metrics_nb.accuracy:.3f}")
    print(f"Naive Bayes F1 Score: {metrics_nb.f1_score:.3f}")

    # Cross-validation
    cv_scores = ModelEvaluator.cross_validate(knn, X_selected, y, cv_folds=5)
    print(
        f"Cross-validation accuracy: {np.mean(cv_scores['accuracy']):.3f} ± {np.std(cv_scores['accuracy']):.3f}"
    )


if __name__ == "__main__":
    main()
