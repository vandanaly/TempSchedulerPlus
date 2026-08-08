import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, classification_report, roc_curve, auc
from sklearn.preprocessing import label_binarize

# ==========================================
# 1. SIMULATED TRAINING DATA (Placeholder)
# ==========================================
epochs = np.arange(1, 51)
# Simulate smooth learning curves
train_acc = 0.5 + 0.45 * (1 - np.exp(-0.1 * epochs)) + np.random.normal(0, 0.01, 50)
val_acc = 0.5 + 0.42 * (1 - np.exp(-0.08 * epochs)) + np.random.normal(0, 0.015, 50)

train_loss = 1.2 * np.exp(-0.1 * epochs) + np.random.normal(0, 0.02, 50)
val_loss = 1.2 * np.exp(-0.08 * epochs) + np.random.normal(0, 0.025, 50)

# Simulate testing data for Confusion Matrix & ROC (Classes: HOT=0, WARM=1, COLD=2)
# Simulating a balanced dataset of 300 files
y_true = np.array([0]*100 + [1]*100 + [2]*100)
y_pred = np.array([0]*92 + [1]*5 + [2]*3 +    # Hot predictions
                  [0]*4 + [1]*90 + [2]*6 +    # Warm predictions
                  [0]*1 + [1]*4 + [2]*95)     # Cold predictions

# Simulated probabilities for ROC
y_score = np.random.rand(300, 3)
for i in range(300):
    y_score[i, y_true[i]] += 1.5  # Boost the correct class probability to simulate a good model
    y_score[i] /= y_score[i].sum()

classes = ['HOT', 'WARM', 'COLD']

# ==========================================
# 2. TRAINING & VALIDATION ACCURACY
# ==========================================
plt.figure(figsize=(8, 5))
plt.plot(epochs, train_acc, label='Training Accuracy', color='blue', linewidth=2)
plt.plot(epochs, val_acc, label='Validation Accuracy', color='orange', linewidth=2)
plt.title('Training and Validation Accuracy over Epochs')
plt.xlabel('Epochs')
plt.ylabel('Accuracy')
plt.legend()
plt.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.savefig('accuracy_curve.png', dpi=300)
plt.close()
print("Saved: accuracy_curve.png")

# ==========================================
# 3. TRAINING & VALIDATION LOSS
# ==========================================
plt.figure(figsize=(8, 5))
plt.plot(epochs, train_loss, label='Training Loss', color='red', linewidth=2)
plt.plot(epochs, val_loss, label='Validation Loss', color='green', linewidth=2)
plt.title('Training and Validation Loss over Epochs')
plt.xlabel('Epochs')
plt.ylabel('Loss')
plt.legend()
plt.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.savefig('loss_curve.png', dpi=300)
plt.close()
print("Saved: loss_curve.png")

# ==========================================
# 4. CONFUSION MATRIX
# ==========================================
cm = confusion_matrix(y_true, y_pred)
plt.figure(figsize=(7, 6))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=classes, yticklabels=classes)
plt.title('Confusion Matrix for Proposed Work')
plt.xlabel('Predicted Tier')
plt.ylabel('Actual Tier')
plt.tight_layout()
plt.savefig('confusion_matrix.png', dpi=300)
plt.close()
print("Saved: confusion_matrix.png")

# ==========================================
# 5. ROC CURVE (Multi-class)
# ==========================================
y_true_bin = label_binarize(y_true, classes=[0, 1, 2])
plt.figure(figsize=(8, 6))
colors = ['darkorange', 'cornflowerblue', 'green']
for i, color in zip(range(3), colors):
    fpr, tpr, _ = roc_curve(y_true_bin[:, i], y_score[:, i])
    roc_auc = auc(fpr, tpr)
    plt.plot(fpr, tpr, color=color, lw=2, label=f'ROC curve of class {classes[i]} (area = {roc_auc:0.2f})')

plt.plot([0, 1], [0, 1], 'k--', lw=2)
plt.xlim([0.0, 1.0])
plt.ylim([0.0, 1.05])
plt.xlabel('False Positive Rate')
plt.ylabel('True Positive Rate')
plt.title('ROC Curve for False Positive and True Positive Rate')
plt.legend(loc="lower right")
plt.grid(True, linestyle='--', alpha=0.7)
plt.tight_layout()
plt.savefig('roc_curve.png', dpi=300)
plt.close()
print("Saved: roc_curve.png")

# ==========================================
# 6. PERFORMANCE MATRICES (Text Output)
# ==========================================
print("\n=== PERFORMANCE MATRICES FOR BALANCED DATASET ===")
report = classification_report(y_true, y_pred, target_names=classes)
print(report)