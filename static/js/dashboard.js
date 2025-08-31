// Dashboard JavaScript functionality

document.addEventListener('DOMContentLoaded', function() {
    // Initialize dashboard
    initializeDashboard();
    
    // Start periodic updates
    startPeriodicUpdates();
    
    // Setup event listeners
    setupEventListeners();
});

function initializeDashboard() {
    // Update footer status on page load
    updateFooterStatus();
    
    // Auto-scroll logs container to bottom
    const logsContainer = document.getElementById('recent-logs');
    if (logsContainer) {
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }
}

function startPeriodicUpdates() {
    // Update status every 30 seconds
    setInterval(updateBotStatus, 30000);
    
    // Update logs every 60 seconds
    setInterval(updateRecentLogs, 60000);
}

function setupEventListeners() {
    // Confirmation for bot start/stop actions
    const botForms = document.querySelectorAll('form[action*="bot"]');
    botForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const isStopAction = this.action.includes('stop_bot');
            const message = isStopAction ? 
                'Are you sure you want to stop the bot?' : 
                'Are you sure you want to start the bot?';
            
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });
    
    // Handle settings form validation
    const settingsForm = document.querySelector('form[action*="settings"]');
    if (settingsForm) {
        settingsForm.addEventListener('submit', validateSettingsForm);
    }
}

function updateBotStatus() {
    fetch('/api/status')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch status');
            }
            return response.json();
        })
        .then(data => {
            // Update status indicator
            const statusIndicator = document.getElementById('status-indicator');
            if (statusIndicator) {
                statusIndicator.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
                statusIndicator.className = `badge ${getStatusBadgeClass(data.status)}`;
            }
            
            // Update uptime display
            const uptimeDisplay = document.getElementById('uptime-display');
            if (uptimeDisplay) {
                const hours = Math.floor(data.uptime / 3600);
                const minutes = Math.floor((data.uptime % 3600) / 60);
                uptimeDisplay.textContent = `${hours}h ${minutes}m`;
            }
            
            // Update actions count
            const actionsDisplay = document.getElementById('actions-display');
            if (actionsDisplay) {
                actionsDisplay.textContent = data.actions_completed || 0;
            }
            
            // Update game state and march status
            updateGameState(data);
            
            // Update footer status
            updateFooterStatus(data.status);
        })
        .catch(error => {
            console.error('Error updating bot status:', error);
            handleApiError('status', error);
        });
}

function updateRecentLogs() {
    fetch('/api/logs')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch logs');
            }
            return response.json();
        })
        .then(data => {
            const logsContainer = document.getElementById('recent-logs');
            if (logsContainer && data.logs && data.logs.length > 0) {
                // Clear existing logs
                logsContainer.innerHTML = '';
                
                // Add new log entries
                data.logs.slice(0, 10).forEach(log => {
                    const logEntry = document.createElement('div');
                    logEntry.className = 'log-entry mb-1';
                    
                    const logContent = document.createElement('small');
                    logContent.className = 'text-muted font-monospace';
                    logContent.textContent = log.trim();
                    
                    // Add color coding based on log level
                    if (log.includes('ERROR')) {
                        logContent.classList.add('text-danger');
                    } else if (log.includes('WARNING')) {
                        logContent.classList.add('text-warning');
                    } else if (log.includes('INFO')) {
                        logContent.classList.add('text-info');
                    }
                    
                    logEntry.appendChild(logContent);
                    logsContainer.appendChild(logEntry);
                });
                
                // Auto-scroll to bottom
                logsContainer.scrollTop = logsContainer.scrollHeight;
            }
        })
        .catch(error => {
            console.error('Error updating logs:', error);
            handleApiError('logs', error);
        });
}

function updateGameState(data) {
    // Update resource displays from game state
    const gameState = data.game_state || {};
    const resources = gameState.resources;
    if (resources) {
        updateResourceDisplay('wood', resources.wood);
        updateResourceDisplay('stone', resources.stone);
        updateResourceDisplay('gold', resources.gold);
        updateResourceDisplay('food', resources.food);
    }
    
    // Update power level
    if (gameState.power_level) {
        const powerDisplay = document.querySelector('.text-info');
        if (powerDisplay && powerDisplay.textContent.includes(',')) {
            powerDisplay.textContent = formatNumber(gameState.power_level);
        }
    }
    
    // Update march status from user processes data
    const userProcesses = data.user_processes || [];
    updateMarchStatus(userProcesses);
}

function updateMarchStatus(userProcesses) {
    // Find march status display elements
    const marchContainers = document.querySelectorAll('.march-status, [data-march-status]');
    
    if (userProcesses && userProcesses.length > 0) {
        userProcesses.forEach((processInfo, index) => {
            const currentMarches = processInfo.current_marches || 0;
            const marchLimit = processInfo.march_limit || 0;
            const instanceName = processInfo.name || 'Bot Instance';
            
            // Update march status for each instance
            const marchElements = document.querySelectorAll(`[data-instance="${processInfo.instance_id}"] .march-info, .march-status-${index}`);
            marchElements.forEach(element => {
                element.textContent = `${currentMarches}/${marchLimit} marches`;
            });
            
            // Update general march status displays
            if (index === 0) { // Use first instance for general display
                const generalMarchElements = document.querySelectorAll('.current-marches, [data-march-current]');
                generalMarchElements.forEach(element => {
                    element.textContent = currentMarches;
                });
                
                const marchLimitElements = document.querySelectorAll('.march-limit, [data-march-limit]');
                marchLimitElements.forEach(element => {
                    element.textContent = marchLimit;
                });
                
                const marchStatusElements = document.querySelectorAll('.march-status-text, [data-march-status-text]');
                marchStatusElements.forEach(element => {
                    element.textContent = `${currentMarches}/${marchLimit}`;
                });
            }
        });
    }
    
    // Update notification panel march data if it exists
    updateNotificationPanelMarches(userProcesses);
}

function updateNotificationPanelMarches(userProcesses) {
    // Preserve march data in notification panel during refresh
    const notificationPanels = document.querySelectorAll('.notification-panel, .bot-status-panel');
    
    notificationPanels.forEach(panel => {
        const marchElements = panel.querySelectorAll('.march-count, .march-status, [data-march-info]');
        
        if (userProcesses && userProcesses.length > 0) {
            const totalMarches = userProcesses.reduce((sum, proc) => sum + (proc.current_marches || 0), 0);
            const totalLimit = userProcesses.reduce((sum, proc) => sum + (proc.march_limit || 0), 0);
            
            marchElements.forEach(element => {
                if (element.classList.contains('march-count')) {
                    element.textContent = totalMarches;
                } else if (element.classList.contains('march-status')) {
                    element.textContent = `${totalMarches}/${totalLimit}`;
                } else if (element.hasAttribute('data-march-info')) {
                    element.textContent = `Marches: ${totalMarches}/${totalLimit}`;
                }
            });
        }
    });
}

function updateResourceDisplay(resourceType, amount) {
    // Find resource display elements and update them
    const resourceElements = document.querySelectorAll(`[data-resource="${resourceType}"], .${resourceType}-display`);
    resourceElements.forEach(element => {
        if (element.tagName === 'SPAN' || element.tagName === 'DIV') {
            element.textContent = formatNumber(amount);
        }
    });
}

function updateFooterStatus(status) {
    const footerStatus = document.getElementById('footer-status');
    if (footerStatus) {
        const statusText = status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown';
        const statusClass = status ? getStatusBadgeClass(status) : 'bg-secondary';
        
        footerStatus.textContent = statusText;
        footerStatus.className = `badge ${statusClass}`;
    }
}

function getStatusBadgeClass(status) {
    switch (status) {
        case 'running':
            return 'bg-success';
        case 'stopped':
            return 'bg-secondary';
        case 'error':
            return 'bg-danger';
        default:
            return 'bg-secondary';
    }
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toLocaleString();
}

function handleApiError(endpoint, error) {
    console.error(`API Error for ${endpoint}:`, error);
    
    // Show user-friendly error message
    const errorMessage = `Failed to update ${endpoint}. The bot may be experiencing issues.`;
    showNotification(errorMessage, 'error');
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
        }
    }, 5000);
}

function validateSettingsForm(e) {
    const form = e.target;
    const gameUrl = form.querySelector('[name="game_url"]');
    const username = form.querySelector('[name="username"]');
    const password = form.querySelector('[name="password"]');
    
    // Check required fields
    if (!gameUrl || !username || !password) {
        e.preventDefault();
        showNotification('Please fill in all required fields.', 'error');
        return false;
    }
    
    // Validate URL format
    try {
        new URL(gameUrl.value);
    } catch (error) {
        e.preventDefault();
        showNotification('Please enter a valid game URL.', 'error');
        return false;
    }
    
    // Validate intervals
    const intervals = form.querySelectorAll('input[name*="interval"]');
    for (let interval of intervals) {
        const value = parseInt(interval.value);
        const min = parseInt(interval.getAttribute('min'));
        const max = parseInt(interval.getAttribute('max'));
        
        if (isNaN(value) || value < min || value > max) {
            e.preventDefault();
            showNotification(`${interval.name.replace('_', ' ')} must be between ${min} and ${max} seconds.`, 'error');
            return false;
        }
    }
    
    return true;
}

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Export functions for use in other scripts
window.dashboardUtils = {
    updateBotStatus,
    updateRecentLogs,
    showNotification,
    formatNumber,
    getStatusBadgeClass
};
