import React from 'react';
import { AlertTriangle, Check, X } from 'lucide-react';

const ConfirmDialog = ({
  isOpen,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  isDestructive = false,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-[#111424] border border-gray-800 rounded-2xl p-6 max-w-sm animate-in fade-in zoom-in">
        <div className="flex items-start gap-3 mb-4">
          {isDestructive && (
            <AlertTriangle className="w-6 h-6 text-red-500 flex-shrink-0 mt-1" />
          )}
          <div>
            <h2 className="text-lg font-bold text-white">{title}</h2>
            <p className="text-gray-400 text-sm mt-1">{message}</p>
          </div>
        </div>
        <div className="flex gap-3 pt-4 border-t border-gray-800">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg font-medium transition flex items-center justify-center gap-2"
          >
            <X className="w-4 h-4" /> {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className={`flex-1 px-4 py-2 rounded-lg font-medium transition flex items-center justify-center gap-2 text-white ${
              isDestructive
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            <Check className="w-4 h-4" /> {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;