// Discord Bot Admin Panel - JavaScript

/**
 * Show alert message to user
 */
function showAlert(message, type = 'info') {
    // Create alert element
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.textContent = message;

    // Insert at top of container
    const container = document.querySelector('.container');
    if (container) {
        container.insertBefore(alert, container.firstChild);
    }

    // Auto-remove after 5 seconds
    setTimeout(() => {
        alert.remove();
    }, 5000);
}

/**
 * Format currency/numbers for display
 */
function formatCurrency(amount) {
    return `${amount.toLocaleString()}`;
}

/**
 * Format timestamp to readable date
 */
function formatDate(timestamp) {
    return new Date(timestamp).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

/**
 * Copy text to clipboard
 */
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showAlert('Copied to clipboard!', 'success');
    }).catch(() => {
        showAlert('Failed to copy', 'error');
    });
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

/**
 * Debounce function for limiting API calls
 */
function debounce(func, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func(...args), delay);
    };
}

/**
 * Make API request with error handling
 */
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, options);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

/**
 * Confirm dialog for destructive actions
 */
function confirmAction(message = 'Are you sure you want to do this?') {
    return confirm(message);
}

/**
 * Initialize tooltips and event listeners
 */
document.addEventListener('DOMContentLoaded', function() {
    // Add any global event listeners here
    console.log('Admin Panel loaded');

    // Highlight active nav link
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.style.background = 'rgba(88, 101, 242, 0.3)';
            link.style.color = '#5865F2';
        }
    });
});

/**
 * Form validation helpers
 */
const FormValidator = {
    /**
     * Validate email format
     */
    isEmail(email) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    },

    /**
     * Validate number is positive
     */
    isPositive(num) {
        return num > 0;
    },

    /**
     * Validate string not empty
     */
    isNotEmpty(str) {
        return str.trim().length > 0;
    },

    /**
     * Validate number within range
     */
    isInRange(num, min, max) {
        return num >= min && num <= max;
    }
};

/**
 * Utility for managing loading states
 */
const LoadingState = {
    show(button) {
        if (button) {
            button.disabled = true;
            button.textContent = '⏳ Loading...';
        }
    },

    hide(button, originalText = 'Save') {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }
};

/**
 * Export data to CSV
 */
function exportToCSV(data, filename) {
    let csv = data.map(row => Object.values(row).join(',')).join('\n');
    let headers = Object.keys(data[0]).join(',');
    csv = headers + '\n' + csv;

    let element = document.createElement('a');
    element.setAttribute('href', 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv));
    element.setAttribute('download', filename);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
}

/**
 * Table sorting - Click on header to sort
 */
function initTableSorting() {
    document.querySelectorAll('th').forEach(header => {
        header.style.cursor = 'pointer';
        header.addEventListener('click', function() {
            const table = this.closest('table');
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            const index = Array.from(this.parentElement.children).indexOf(this);
            const ascending = !this.dataset.ascending;

            rows.sort((a, b) => {
                const aValue = a.children[index].textContent;
                const bValue = b.children[index].textContent;

                // Try numeric comparison first
                const aNum = parseFloat(aValue);
                const bNum = parseFloat(bValue);

                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return ascending ? aNum - bNum : bNum - aNum;
                }

                // Fall back to string comparison
                return ascending
                    ? aValue.localeCompare(bValue)
                    : bValue.localeCompare(aValue);
            });

            rows.forEach(row => table.querySelector('tbody').appendChild(row));
            this.dataset.ascending = ascending;
        });
    });
}

// Initialize table sorting when DOM loads
document.addEventListener('DOMContentLoaded', initTableSorting);

/**
 * Real-time form validation
 */
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return false;

    let isValid = true;
    form.querySelectorAll('input[required], select[required]').forEach(field => {
        if (!field.value.trim()) {
            field.style.borderColor = '#ED4245';
            isValid = false;
        } else {
            field.style.borderColor = '';
        }
    });

    return isValid;
}

/**
 * Add keyboard shortcuts
 */
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + S to save (for forms)
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        const form = document.querySelector('form');
        if (form && form.querySelector('.btn-primary')) {
            form.querySelector('.btn-primary').click();
        }
    }

    // Escape to close alerts
    if (e.key === 'Escape') {
        document.querySelectorAll('.alert').forEach(alert => alert.remove());
    }
});
