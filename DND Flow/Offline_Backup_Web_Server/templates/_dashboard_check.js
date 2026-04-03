
        const TAB_PATHS = {
            overview: '/overview',
            server: '/serverconfig',
            shop: '/shop',
            jobs: '/jobs',
            items: '/items',
            settings: '/settings',
            audit: '/audit',
            users: '/users'
        };

        let currentDashboardTab = null;
        let usersSyncTimer = null;
        let usersSyncInFlight = false;
        let _usersListenerAttached = false;
        let dashboardItemCatalog = [];
        const INITIAL_USER_ID = '{{ initial_user_id or "" }}' || null;
        const INITIAL_SHEET_ID = '{{ initial_sheet_id or "" }}' || null;
        let pendingUsersNavigation = INITIAL_USER_ID ? { userId: INITIAL_USER_ID, sheetId: INITIAL_SHEET_ID } : null;

        // Tab switching
        function switchTab(tabName, buttonEl = null, updateUrl = true) {
            currentDashboardTab = tabName;

            // Hide all tabs
            const tabs = document.querySelectorAll('.tab-content');
            tabs.forEach(tab => tab.classList.remove('active'));

            // Remove active from all buttons
            const buttons = document.querySelectorAll('.tab-btn');
            buttons.forEach(btn => btn.classList.remove('active'));

            // Show selected tab
            document.getElementById(tabName).classList.add('active');

            // Mark button as active
            const activeButton = buttonEl || document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
            if (activeButton) {
                activeButton.classList.add('active');
            }

            if (updateUrl) {
                const newPath = TAB_PATHS[tabName] || '/overview';
                if (window.location.pathname !== newPath) {
                    history.pushState({ tab: tabName }, '', newPath);
                }
            }

            // Load data for the tab
            if (tabName === 'overview') loadOverview();
            if (tabName === 'server') loadServerData();
            if (tabName === 'shop') loadShopData();
            if (tabName === 'jobs') loadJobsData();
            if (tabName === 'items') loadItemsData();
            if (tabName === 'settings') loadSettingsData();
            if (tabName === 'audit') loadAuditData();
            if (tabName === 'users') loadUsersData();

            if (tabName === 'users') {
                startUsersAutoSync();
            } else {
                stopUsersAutoSync();
            }
        }

        // Alert helper
        function showAlert(tabId, message, type = 'success') {
            const alertEl = document.getElementById(`alert-${tabId}`);
            alertEl.textContent = message;
            alertEl.className = `alert show alert-${type}`;
            setTimeout(() => alertEl.classList.remove('show'), 5000);
        }

        // API helper
        async function apiCall(method, endpoint, data = null) {
            try {
                const upperMethod = String(method || '').toUpperCase();
                const options = {
                    method,
                    headers: { 'Content-Type': 'application/json' }
                };
                if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(upperMethod)) {
                    options.headers['X-Audit-Actor'] = getAuditActor();
                    options.headers['X-Audit-Source'] = 'admin_webpage';
                }
                if (data) options.body = JSON.stringify(data);

                const response = await fetch(`/api${endpoint}`, options);
                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'API error');
                }
                return result;
            } catch (error) {
                console.error('API Error:', error);
                throw error;
            }
        }

        function getAuditActor() {
            const stored = localStorage.getItem('dashboardAuditActor');
            return (stored && stored.trim()) ? stored.trim() : 'Local Admin';
        }

        function saveAuditActor() {
            const input = document.getElementById('audit-actor-name');
            const value = String(input?.value || '').trim();
            localStorage.setItem('dashboardAuditActor', value || 'Local Admin');
            if (input) {
                input.value = value || 'Local Admin';
            }
            showAlert('audit', 'Audit editor name saved.', 'success');
        }

        function _formatAuditTime(isoValue) {
            try {
                return new Date(isoValue).toLocaleString();
            } catch (e) {
                return isoValue || 'Unknown time';
            }
        }

        function parseAuditDetails(rawDetails) {
            if (rawDetails == null) return null;
            if (typeof rawDetails === 'object') return rawDetails;
            try {
                return JSON.parse(rawDetails);
            } catch (e) {
                return rawDetails;
            }
        }

        function auditUsername(actorValue) {
            const actor = String(actorValue || 'Unknown').trim();
            const idx = actor.lastIndexOf(' (');
            if (idx > 0) return actor.slice(0, idx).trim();
            return actor;
        }

        function auditSourceLabel(sourceValue) {
            if (sourceValue === 'discord_bot') return 'Bot Command';
            if (sourceValue === 'admin_webpage') return 'Website';
            return sourceValue || 'Unknown';
        }

        function stringifyAuditValue(value) {
            if (value == null) return 'None';
            if (typeof value === 'string') return value || 'None';
            try {
                return JSON.stringify(value, null, 2);
            } catch (e) {
                return String(value);
            }
        }

        function flattenAuditOptionLines(options, prefix = '') {
            const lines = [];
            for (const option of Array.isArray(options) ? options : []) {
                if (!option || typeof option !== 'object') continue;
                const name = String(option.name || '').trim();
                const path = [prefix, name].filter(Boolean).join(' ').trim();
                if (Object.prototype.hasOwnProperty.call(option, 'value')) {
                    lines.push(`${path || 'value'}: ${formatAuditScalar(option.value)}`);
                    continue;
                }
                lines.push(...flattenAuditOptionLines(option.options || [], path));
            }
            return lines;
        }

        function formatAuditScalar(value) {
            if (value == null || value === '') return 'None';
            if (typeof value === 'string') return value;
            if (typeof value === 'number' || typeof value === 'boolean') return String(value);
            try {
                return JSON.stringify(value);
            } catch (e) {
                return String(value);
            }
        }

        function formatAuditBlock(value) {
            if (value == null) return 'None';
            if (typeof value === 'string') return value || 'None';
            if (typeof value === 'number' || typeof value === 'boolean') return String(value);

            if (Array.isArray(value)) {
                const optionLines = flattenAuditOptionLines(value);
                if (optionLines.length) return optionLines.join('\n');
                if (!value.length) return 'None';
                return value.map((item, index) => `${index + 1}. ${formatAuditScalar(item)}`).join('\n');
            }

            if (typeof value === 'object') {
                const entries = Object.entries(value);
                if (!entries.length) return 'None';
                return entries.map(([key, entryValue]) => {
                    if (entryValue && typeof entryValue === 'object') {
                        const nested = formatAuditBlock(entryValue);
                        if (!nested.includes('\n')) {
                            return `${key}: ${nested}`;
                        }
                        return `${key}:\n${nested.split('\n').map(line => `  ${line}`).join('\n')}`;
                    }
                    return `${key}: ${formatAuditScalar(entryValue)}`;
                }).join('\n');
            }

            return stringifyAuditValue(value);
        }

        function getAuditColumnData(row) {
            const details = parseAuditDetails(row.request_details);
            const isObject = details && typeof details === 'object' && !Array.isArray(details);

            const commandUsed = row.source === 'discord_bot'
                ? (isObject ? details.command : null) || row.action || row.route || 'None'
                : (row.action || row.route || 'None');

            const channelName = row.source === 'discord_bot'
                ? ((isObject ? details.channel_name : null) || 'None')
                : 'None';

            const fullCommand = row.source === 'discord_bot'
                ? ((isObject ? details.full_command : null) || commandUsed || 'None')
                : `${row.method || ''} ${row.route || ''}`.trim() || 'None';

            const inputData = isObject
                ? (details.input_data ?? details.options ?? details)
                : (details ?? 'None');

            const previousData = isObject
                ? (details.previous_data ?? details.previous ?? details.before ?? 'None')
                : 'None';

            const nextData = isObject
                ? (details.next_data ?? details.next ?? details.after ?? 'None')
                : 'None';

            return {
                dateTime: _formatAuditTime(row.created_at),
                username: auditUsername(row.actor),
                sourceLabel: auditSourceLabel(row.source),
                commandUsed,
                channelName,
                fullCommand,
                inputData: formatAuditBlock(inputData),
                previousData: formatAuditBlock(previousData),
                nextData: formatAuditBlock(nextData),
            };
        }

        function getAuditSearchParams() {
            const q = document.getElementById('audit-search-q')?.value?.trim() || '';
            const actor = document.getElementById('audit-search-actor')?.value?.trim() || '';
            const where = document.getElementById('audit-search-where')?.value?.trim() || '';
            const source = document.getElementById('audit-search-source')?.value?.trim() || '';

            const params = new URLSearchParams();
            params.set('limit', '100');
            if (q) params.set('q', q);
            if (actor) params.set('actor', actor);
            if (where) params.set('where', where);
            if (source) params.set('source', source);
            return params.toString();
        }

        function clearAuditFilters() {
            const q = document.getElementById('audit-search-q');
            const actor = document.getElementById('audit-search-actor');
            const where = document.getElementById('audit-search-where');
            const source = document.getElementById('audit-search-source');
            if (q) q.value = '';
            if (actor) actor.value = '';
            if (where) where.value = '';
            if (source) source.value = '';
            loadAuditLogs();
        }

        async function loadAuditData() {
            const auditActorInput = document.getElementById('audit-actor-name');
            if (auditActorInput) {
                auditActorInput.value = getAuditActor();
            }
            await loadAuditLogs();
        }

        async function loadAuditLogs() {
            try {
                const rows = await apiCall('GET', `/audit-logs?${getAuditSearchParams()}`);
                const list = document.getElementById('audit-log-list');

                if (!rows || !rows.length) {
                    list.innerHTML = '<p style="text-align: center; color: #999; padding: 20px;">No audit entries yet</p>';
                    return;
                }

                const bodyRows = rows.map(row => {
                    const view = getAuditColumnData(row);
                    const rowClass = Number(row.id || 0) % 2 === 0 ? 'audit-entry-alt' : '';
                    return `
                        <tr class="audit-entry-start ${rowClass}">
                            <td>
                                <div class="audit-cell-label">Date and Time</div>
                                <div class="audit-cell-value">${escHtml(view.dateTime)}</div>
                            </td>
                            <td>
                                <div class="audit-cell-label">Username</div>
                                <div class="audit-cell-value">${escHtml(view.username)}</div>
                            </td>
                            <td>
                                <div class="audit-cell-label">Botcommand/Website based</div>
                                <span class="audit-pill">${escHtml(view.sourceLabel)}</span>
                            </td>
                        </tr>
                        <tr class="${rowClass}">
                            <td colspan="2">
                                <div class="audit-cell-label">Command/Button used</div>
                                <div class="audit-cell-value">${escHtml(view.commandUsed)}</div>
                            </td>
                            <td>
                                <div class="audit-cell-label">Channel name</div>
                                <div class="audit-cell-value">${escHtml(view.channelName || 'None')}</div>
                            </td>
                        </tr>
                        <tr class="${rowClass}">
                            <td colspan="3">
                                <div class="audit-cell-label">Full command</div>
                                <code class="audit-code">${escHtml(view.fullCommand)}</code>
                            </td>
                        </tr>
                        <tr class="${rowClass}">
                            <td colspan="3">
                                <div class="audit-cell-label">Input data</div>
                                <code class="audit-code">${escHtml(view.inputData)}</code>
                            </td>
                        </tr>
                        <tr class="${rowClass}">
                            <td colspan="3">
                                <div class="audit-cell-label">Previous data</div>
                                <code class="audit-code">${escHtml(view.previousData)}</code>
                            </td>
                        </tr>
                        <tr class="${rowClass}">
                            <td colspan="3">
                                <div class="audit-cell-label">Next data</div>
                                <code class="audit-code">${escHtml(view.nextData)}</code>
                            </td>
                        </tr>
                    `;
                }).join('');

                list.innerHTML = `
                    <div class="audit-table-wrap">
                        <table class="audit-table">
                            <thead>
                                <tr>
                                    <th colspan="3">Recent Entries (last 30 days)</th>
                                </tr>
                            </thead>
                            <tbody>${bodyRows}</tbody>
                        </table>
                    </div>
                `;
            } catch (error) {
                showAlert('audit', 'Failed to load audit logs: ' + error.message, 'error');
            }
        }

        async function loadDashboardItemCatalog(force = false) {
            if (!force && dashboardItemCatalog.length) {
                return dashboardItemCatalog;
            }

            const items = await apiCall('GET', '/items');
            dashboardItemCatalog = (items || [])
                .map(item => String(item.name || '').trim())
                .filter(Boolean)
                .sort((left, right) => left.localeCompare(right));
            return dashboardItemCatalog;
        }

        // ===== OVERVIEW =====
        async function loadOverview() {
            try {
                const shop = await apiCall('GET', '/shop');
                const jobs = await apiCall('GET', '/jobs');
                const items = await apiCall('GET', '/items');
                const info = await apiCall('GET', '/info');

                document.getElementById('stat-servers').textContent = info.live_server_count ?? '--';
                document.getElementById('stat-shop-items').textContent = shop.length;
                document.getElementById('stat-jobs').textContent = jobs.length;
                document.getElementById('stat-items').textContent = items.length;
            } catch (error) {
                showAlert('overview', 'Failed to load overview: ' + error.message, 'error');
            }
        }

        // ===== SERVER CONFIG =====
        let selectedServerId = null;

        function getServerDisplayName(server) {
            if (server?.guild_name) {
                return `${server.guild_name} (${server.guild_id})`;
            }
            return `Guild ${server?.guild_id || ''}`;
        }

        function syncSheetServerDropdown(servers) {
            const select = document.getElementById('sheet-server-select');
            const previousValue = selectedServerId && servers.some(server => server.guild_id === selectedServerId)
                ? selectedServerId
                : '';

            select.innerHTML = '<option value="">Select a server</option>';
            servers.forEach(server => {
                const option = document.createElement('option');
                option.value = server.guild_id;
                option.textContent = getServerDisplayName(server);
                select.appendChild(option);
            });
            select.value = previousValue;
        }

        function setSheetFieldsVisibility(isVisible) {
            document.getElementById('sheet-fields-section').style.display = isVisible ? 'block' : 'none';
            document.getElementById('sheet-fields-empty').style.display = isVisible ? 'none' : 'block';
        }

        function populateServerForm(server) {
            document.getElementById('server-id').value = server?.guild_id || '';
            document.getElementById('admin-role').value = server?.admin_role_id || '';
            document.getElementById('admin-channel').value = server?.admin_channel_id || '';
            document.getElementById('member-role').value = server?.member_role_id || '';
            document.getElementById('member-channel').value = server?.member_channel_id || '';
        }

        async function selectServerConfig(serverId) {
            if (!serverId) {
                selectedServerId = null;
                populateServerForm(null);
                document.getElementById('fields-list').innerHTML = '<p style="text-align: center; color: #999; padding: 20px;">Select a server to manage sheet fields</p>';
                document.getElementById('sheet-server-select').value = '';
                setSheetFieldsVisibility(false);
                return;
            }
            selectedServerId = serverId;
            document.getElementById('sheet-server-select').value = serverId;
            try {
                const server = await apiCall('GET', `/servers/${serverId}`);
                populateServerForm(server || {});
                const fields = await apiCall('GET', `/servers/${serverId}/fields`);
                displayFields(fields, serverId);
                setSheetFieldsVisibility(true);
            } catch (error) {
                setSheetFieldsVisibility(false);
                showAlert('server', 'Failed to load server config: ' + error.message, 'error');
            }
        }

        function handleSheetServerSelection(serverId) {
            selectServerConfig(serverId);
        }

        function displayConfiguredServers(servers) {
            const list = document.getElementById('server-config-list');
            if (!servers.length) {
                list.innerHTML = '<p style="text-align: center; color: #999; padding: 20px;">No configured server entries</p>';
                return;
            }

            list.innerHTML = servers.map(server => {
                const isActive = selectedServerId === server.guild_id;
                const title = getServerDisplayName(server);
                return `
                    <div class="list-item">
                        <div class="list-item-info">
                            <div class="list-item-title">${title}</div>
                            <div class="list-item-detail">Admin channel: ${server.admin_channel_id || 'None'} | Member channel: ${server.member_channel_id || 'None'}</div>
                        </div>
                        <div style="display:flex; gap:8px;">
                            <button class="btn-secondary" onclick="selectServerConfig('${server.guild_id}')" ${isActive ? 'disabled' : ''}>${isActive ? 'Loaded' : 'Load'}</button>
                            <button class="btn-danger" onclick="removeServerConfig('${server.guild_id}')">Remove</button>
                        </div>
                    </div>`;
            }).join('');
        }

        async function loadServerData() {
            try {
                const servers = await apiCall('GET', '/servers');
                displayConfiguredServers(servers);
                syncSheetServerDropdown(servers);

                if (selectedServerId && servers.some(server => server.guild_id === selectedServerId)) {
                    await selectServerConfig(selectedServerId);
                } else {
                    selectedServerId = null;
                    populateServerForm(null);
                    document.getElementById('fields-list').innerHTML = servers.length
                        ? '<p style="text-align: center; color: #999; padding: 20px;">Select a server to manage sheet fields</p>'
                        : '<p style="text-align: center; color: #999; padding: 20px;">Add a server first</p>';
                    setSheetFieldsVisibility(false);
                }
            } catch (error) {
                setSheetFieldsVisibility(false);
                showAlert('server', 'Failed to load server data: ' + error.message, 'error');
            }
        }

        async function saveServer() {
            try {
                const serverId = document.getElementById('server-id').value.trim();
                if (!serverId) {
                    showAlert('server', 'Please enter a Server ID', 'error');
                    return;
                }

                const data = {
                    admin_role_id: document.getElementById('admin-role').value.trim() || null,
                    admin_channel_id: document.getElementById('admin-channel').value.trim() || null,
                    member_role_id: document.getElementById('member-role').value.trim() || null,
                    member_channel_id: document.getElementById('member-channel').value.trim() || null
                };

                await apiCall('POST', `/servers/${serverId}`, data);
                selectedServerId = serverId;
                showAlert('server', 'Server configuration saved!', 'success');
                loadServerData();
            } catch (error) {
                showAlert('server', 'Error: ' + error.message, 'error');
            }
        }

        function displayFields(fields, serverId) {
            const list = document.getElementById('fields-list');
            if (fields.length === 0) {
                list.innerHTML = '<p style="text-align: center; color: #999; padding: 20px;">No custom fields yet</p>';
                return;
            }

            list.innerHTML = fields.map(field => `
                <div class="list-item">
                    <div class="list-item-info">
                        <div class="list-item-title">${field}</div>
                        <div class="list-item-detail">${field.toLowerCase() === 'status' || field.toLowerCase() === 'name' ? 'Permanent field' : 'Custom field'}</div>
                    </div>
                    ${field.toLowerCase() !== 'status' && field.toLowerCase() !== 'name' ?
                        `<button class="btn-danger" onclick="deleteField('${field}', '${serverId}')">Remove</button>` : ''}
                </div>
            `).join('');
        }

        async function addField() {
            try {
                const serverId = document.getElementById('server-id').value.trim();
                const fieldName = document.getElementById('field-name').value.trim();

                if (!serverId) {
                    showAlert('server', 'Please enter a Server ID first', 'error');
                    return;
                }
                if (!fieldName) {
                    showAlert('server', 'Please enter a field name', 'error');
                    return;
                }

                await apiCall('POST', `/servers/${serverId}/fields`, { field_name: fieldName });
                showAlert('server', `Field "${fieldName}" added!`, 'success');
                document.getElementById('field-name').value = '';
                loadServerData();
            } catch (error) {
                showAlert('server', 'Error: ' + error.message, 'error');
            }
        }

        async function deleteField(fieldName, serverId) {
            if (!confirm(`Delete field "${fieldName}"?`)) return;
            try {
                await apiCall('DELETE', `/servers/${serverId}/fields/${fieldName}`);
                showAlert('server', `Field "${fieldName}" removed!`, 'success');
                loadServerData();
            } catch (error) {
                showAlert('server', 'Error: ' + error.message, 'error');
            }
        }

        async function removeServerConfig(serverId) {
            if (!confirm(`Remove saved server configuration for ${serverId}?`)) return;
            try {
                await apiCall('DELETE', `/servers/${serverId}`);
                if (selectedServerId === serverId) {
                    selectedServerId = null;
                }
                showAlert('server', `Server configuration ${serverId} removed!`, 'success');
                loadServerData();
                loadOverview();
            } catch (error) {
                showAlert('server', 'Error: ' + error.message, 'error');
            }
        }

        async function resetServerConfig() {
            if (!confirm('Reset Server Configuration and remove all saved server entries and sheet fields?')) return;
            try {
                await apiCall('DELETE', '/servers');
                selectedServerId = null;
                populateServerForm(null);
                document.getElementById('sheet-server-select').value = '';
                document.getElementById('fields-list').innerHTML = '<p style="text-align: center; color: #999; padding: 20px;">Add a server first</p>';
                setSheetFieldsVisibility(false);
                showAlert('server', 'All server configuration entries were removed.', 'success');
                loadServerData();
                loadOverview();
            } catch (error) {
                showAlert('server', 'Error: ' + error.message, 'error');
            }
        }

        // ===== SHOP =====
        async function loadShopData() {
            try {
                // Load items for dropdown
                const items = await loadDashboardItemCatalog(true);
                const select = document.getElementById('shop-item-select');
                select.innerHTML = '<option value="">-- Choose an item --</option>';
                items.forEach(itemName => {
                    const option = document.createElement('option');
                    option.value = itemName;
                    option.textContent = itemName;
                    select.appendChild(option);
                });

                // Load shop items
                const shopItems = await apiCall('GET', '/shop');
                displayShopItems(shopItems);
            } catch (error) {
                showAlert('shop', 'Failed to load shop: ' + error.message, 'error');
            }
        }

        function displayShopItems(items) {
            const list = document.getElementById('shop-list');
            if (items.length === 0) {
                list.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🏪</div><p>No items in shop yet</p></div>';
                return;
            }

            list.innerHTML = items.map(item => `
                <div class="list-item" style="flex-wrap: wrap; gap: 10px; align-items: flex-start;">
                    <div style="min-width: 80px; width: 80px; height: 80px; background: #f0f0f0; border-radius: 5px; display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; position: relative;">
                        <img src="/api/items/${encodeURIComponent(item.item_name)}/image" alt="${item.item_name}" class="shop-item-thumb" style="width: 100%; height: 100%; object-fit: cover;">
                        <div class="shop-item-thumb-placeholder">📦</div>
                    </div>
                    <div class="list-item-info" style="flex: 1; min-width: 200px;">
                        <div class="list-item-title">${item.item_name}</div>
                        <div class="list-item-detail">💰 Price: ${item.price}</div>
                    </div>
                    <button class="btn-danger" onclick="deleteShopItem('${item.item_name}')">Remove</button>
                </div>
            `).join('');

            // Handle image load/error
            document.querySelectorAll('.shop-item-thumb').forEach(img => {
                img.onload = () => {
                    img.nextElementSibling.style.display = 'none';
                };
                img.onerror = () => {
                    img.style.display = 'none';
                    img.nextElementSibling.style.display = 'flex';
                };
            });
        }

        async function addShopItem() {
            try {
                const itemName = document.getElementById('shop-item-select').value.trim();
                const price = parseInt(document.getElementById('shop-item-price').value);

                if (!itemName) {
                    showAlert('shop', 'Please select an item', 'error');
                    return;
                }
                if (isNaN(price) || price < 0) {
                    showAlert('shop', 'Please enter valid price', 'error');
                    return;
                }

                await apiCall('POST', '/shop', { item_name: itemName, price });
                showAlert('shop', `"${itemName}" added to shop!`, 'success');
                document.getElementById('shop-item-select').value = '';
                document.getElementById('shop-item-price').value = '';
                loadShopData();
            } catch (error) {
                showAlert('shop', 'Error: ' + error.message, 'error');
            }
        }

        async function deleteShopItem(itemName) {
            if (!confirm(`Delete "${itemName}" from shop?`)) return;
            try {
                await apiCall('DELETE', `/shop/${encodeURIComponent(itemName)}`);
                showAlert('shop', `"${itemName}" removed!`, 'success');
                loadShopData();
            } catch (error) {
                showAlert('shop', 'Error: ' + error.message, 'error');
            }
        }

        async function resetShop() {
            if (!confirm('Reset Shop and remove all shop entries?')) return;
            try {
                await apiCall('DELETE', '/shop');
                document.getElementById('shop-item-select').value = '';
                document.getElementById('shop-item-price').value = '';
                showAlert('shop', 'All shop entries were removed.', 'success');
                loadShopData();
                loadOverview();
            } catch (error) {
                showAlert('shop', 'Error: ' + error.message, 'error');
            }
        }

        // ===== JOBS =====
        async function loadJobsData() {
            try {
                const jobs = await apiCall('GET', '/jobs');
                displayJobs(jobs);
            } catch (error) {
                showAlert('jobs', 'Failed to load jobs: ' + error.message, 'error');
            }
        }

        function displayJobs(jobs) {
            const list = document.getElementById('jobs-list');
            if (jobs.length === 0) {
                list.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💼</div><p>No jobs created yet</p></div>';
                return;
            }

            list.innerHTML = jobs.map(job => `
                <div class="list-item">
                    <div class="list-item-info">
                        <div class="list-item-title">${job.job_name}</div>
                        <div class="list-item-detail">💵 Payment: ${parseFloat(job.payment).toFixed(2)}</div>
                    </div>
                    <button class="btn-danger" onclick="deleteJob('${job.job_name}')">Remove</button>
                </div>
            `).join('');
        }

        async function addJob() {
            try {
                const name = document.getElementById('job-name').value.trim();
                const payment = parseFloat(document.getElementById('job-payment').value);

                if (!name) {
                    showAlert('jobs', 'Please enter job name', 'error');
                    return;
                }
                if (isNaN(payment) || payment < 0) {
                    showAlert('jobs', 'Please enter valid payment', 'error');
                    return;
                }

                await apiCall('POST', '/jobs', { job_name: name, payment });
                showAlert('jobs', `Job "${name}" created!`, 'success');
                document.getElementById('job-name').value = '';
                document.getElementById('job-payment').value = '';
                loadJobsData();
            } catch (error) {
                showAlert('jobs', 'Error: ' + error.message, 'error');
            }
        }

        async function deleteJob(jobName) {
            if (!confirm(`Delete job "${jobName}"?`)) return;
            try {
                await apiCall('DELETE', `/jobs/${encodeURIComponent(jobName)}`);
                showAlert('jobs', `Job "${jobName}" removed!`, 'success');
                loadJobsData();
            } catch (error) {
                showAlert('jobs', 'Error: ' + error.message, 'error');
            }
        }

        async function resetJobs() {
            if (!confirm('Reset Jobs and remove all job entries?')) return;
            try {
                await apiCall('DELETE', '/jobs');
                document.getElementById('job-name').value = '';
                document.getElementById('job-payment').value = '';
                showAlert('jobs', 'All job entries were removed.', 'success');
                loadJobsData();
                loadOverview();
            } catch (error) {
                showAlert('jobs', 'Error: ' + error.message, 'error');
            }
        }

        // ===== ITEMS =====
        async function loadItemsData() {
            try {
                const items = await apiCall('GET', '/items');
                displayItems(items);
            } catch (error) {
                showAlert('items', 'Failed to load items: ' + error.message, 'error');
            }
        }

        function displayItems(items) {
            const list = document.getElementById('items-list');
            if (items.length === 0) {
                list.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎁</div><p>No items created yet</p></div>';
                return;
            }

            list.innerHTML = items.map(item => `
                <div class="list-item" style="flex-wrap: wrap; gap: 10px; align-items: flex-start;">
                    <div style="min-width: 80px; width: 80px; height: 80px; background: #f0f0f0; border-radius: 5px; display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0;">
                        ${item.image ? `<img src="/api/items/${encodeURIComponent(item.name)}/image" alt="${item.name}" style="width: 100%; height: 100%; object-fit: cover;">` : '<div style="font-size: 30px;">📦</div>'}
                    </div>
                    <div class="list-item-info" style="flex: 1; min-width: 200px;">
                        <div class="list-item-title">${item.name}</div>
                        <div class="list-item-detail">
                            Consumable: <strong>${item.consumable}</strong> | Image: ${item.image ? '✓' : 'None'}
                        </div>
                        <div class="list-item-detail" style="color: #888; margin-top: 5px;">
                            ${item.description || 'No description'}
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn-secondary" style="padding: 6px 12px; font-size: 0.85em;" onclick="uploadItemImage('${item.name}')">Upload Image</button>
                        <button class="btn-danger" onclick="deleteItem('${item.name}')">Remove</button>
                    </div>
                </div>
            `).join('');
        }

        async function addItem() {
            try {
                const name = document.getElementById('new-item-name').value.trim();
                const consumable = document.getElementById('item-consumable').value;
                const description = document.getElementById('item-description').value.trim();
                const imageFile = document.getElementById('item-image').files[0];

                if (!name) {
                    showAlert('items', 'Please enter item name', 'error');
                    return;
                }

                // First create the item
                await apiCall('POST', '/items', { name, consumable, description });
                showAlert('items', `"${name}" created!`, 'success');

                // Then upload image if provided
                if (imageFile) {
                    const formData = new FormData();
                    formData.append('file', imageFile);
                    try {
                        const response = await fetch(`/api/items/${encodeURIComponent(name)}/image`, {
                            method: 'POST',
                            body: formData
                        });
                        const data = await response.json();
                        if (data.status === 'success') {
                            showAlert('items', 'Image uploaded!', 'success');
                        }
                    } catch (imgError) {
                        console.warn('Image upload failed (non-fatal):', imgError);
                    }
                }

                document.getElementById('new-item-name').value = '';
                document.getElementById('item-consumable').value = 'No';
                document.getElementById('item-description').value = '';
                document.getElementById('item-image').value = '';
                loadItemsData();
            } catch (error) {
                showAlert('items', 'Error: ' + error.message, 'error');
            }
        }

        function uploadItemImage(itemName) {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.addEventListener('change', async (e) => {
                const file = e.target.files[0];
                if (!file) return;

                const formData = new FormData();
                formData.append('file', file);

                try {
                    const response = await fetch(`/api/items/${encodeURIComponent(itemName)}/image`, {
                        method: 'POST',
                        body: formData
                    });
                    const data = await response.json();
                    if (data.status === 'success') {
                        showAlert('items', 'Image uploaded!', 'success');
                        loadItemsData();
                    } else {
                        showAlert('items', 'Error: ' + data.error, 'error');
                    }
                } catch (error) {
                    showAlert('items', 'Error: ' + error.message, 'error');
                }
            });
            input.click();
        }

        async function deleteItem(itemName) {
            if (!confirm(`Delete item "${itemName}"?`)) return;
            try {
                await apiCall('DELETE', `/items/${encodeURIComponent(itemName)}`);
                showAlert('items', `"${itemName}" removed!`, 'success');
                loadItemsData();
            } catch (error) {
                showAlert('items', 'Error: ' + error.message, 'error');
            }
        }

        async function resetItems() {
            if (!confirm('Reset Items and remove all items and uploaded images?')) return;
            try {
                await apiCall('DELETE', '/items');
                document.getElementById('new-item-name').value = '';
                document.getElementById('item-consumable').value = 'No';
                document.getElementById('item-description').value = '';
                document.getElementById('item-image').value = '';
                showAlert('items', 'All items were removed.', 'success');
                loadItemsData();
                loadOverview();
            } catch (error) {
                showAlert('items', 'Error: ' + error.message, 'error');
            }
        }

        // ===== SETTINGS =====
        async function loadSettingsData() {
            try {
                const workCooldown = await apiCall('GET', '/settings/work-cooldown');
                const deathCooldown = await apiCall('GET', '/settings/death-cooldown');
                const combatRules = await apiCall('GET', '/settings/combat-rules');
                const info = await apiCall('GET', '/info');

                document.getElementById('work-cooldown').value = workCooldown.days || 0;
                document.getElementById('death-cooldown').value = deathCooldown.days || 0;
                document.getElementById('death-infinite').value = deathCooldown.infinite ? 'true' : 'false';
                document.getElementById('combat-solid-hit').value = combatRules.solid_hit;
                document.getElementById('combat-small-hit').value = combatRules.small_hit;
                document.getElementById('combat-miss').value = combatRules.miss;
                document.getElementById('combat-self-hit').value = combatRules.self_hit;

                const dbStatus = Object.entries(info.databases)
                    .map(([db, exists]) => `<p>${exists ? '🟢' : '🔴'} <strong>${db}</strong></p>`)
                    .join('');

                document.getElementById('db-info').innerHTML = `
                    <p><strong>Bot Directory:</strong> ${info.bot_dir}</p>
                    <p style="margin: 15px 0; border-top: 1px solid #e0e0e0; padding-top: 15px;"><strong>Database Status:</strong></p>
                    ${dbStatus}
                `;

            } catch (error) {
                showAlert('settings', 'Failed to load settings: ' + error.message, 'error');
            }
        }

        async function saveWorkCooldown() {
            try {
                const days = parseInt(document.getElementById('work-cooldown').value);
                if (isNaN(days) || days < 0) {
                    showAlert('settings', 'Please enter valid days', 'error');
                    return;
                }

                await apiCall('POST', '/settings/work-cooldown', { days });
                showAlert('settings', `Work cooldown set to ${days} day(s)!`, 'success');
            } catch (error) {
                showAlert('settings', 'Error: ' + error.message, 'error');
            }
        }

        async function saveDeathSettings() {
            try {
                const days = parseInt(document.getElementById('death-cooldown').value);
                const infinite = document.getElementById('death-infinite').value === 'true';
                if (isNaN(days) || days < 0) {
                    showAlert('settings', 'Please enter valid days', 'error');
                    return;
                }

                await apiCall('POST', '/settings/death-cooldown', { days, infinite });
                showAlert('settings', `Death settings updated: ${days} day(s), infinite ${infinite ? 'enabled' : 'disabled'}.`, 'success');
            } catch (error) {
                showAlert('settings', 'Error: ' + error.message, 'error');
            }
        }

        async function saveCombatRules() {
            try {
                const solidHit = parseFloat(document.getElementById('combat-solid-hit').value);
                const smallHit = parseFloat(document.getElementById('combat-small-hit').value);
                const miss = parseFloat(document.getElementById('combat-miss').value);
                const selfHit = parseFloat(document.getElementById('combat-self-hit').value);

                const values = [solidHit, smallHit, miss, selfHit];
                if (values.some(v => Number.isNaN(v) || v < 0)) {
                    showAlert('settings', 'Please enter valid non-negative combat rule values', 'error');
                    return;
                }

                const total = solidHit + smallHit + miss + selfHit;
                if (Math.abs(total - 1.0) > 0.0001) {
                    showAlert('settings', 'Combat rule values must sum to 1.0', 'error');
                    return;
                }

                await apiCall('POST', '/settings/combat-rules', {
                    solid_hit: solidHit,
                    small_hit: smallHit,
                    miss,
                    self_hit: selfHit
                });
                showAlert('settings', 'Combat rules updated!', 'success');
            } catch (error) {
                showAlert('settings', 'Error: ' + error.message, 'error');
            }
        }

        async function resetSettings() {
            if (!confirm('Reset Settings back to default values?')) return;
            try {
                await apiCall('POST', '/settings/reset');
                await loadSettingsData();
                showAlert('settings', 'Settings were reset to defaults.', 'success');
            } catch (error) {
                showAlert('settings', 'Error: ' + error.message, 'error');
            }
        }

        // ===== USERS =====

        function startUsersAutoSync() {
            stopUsersAutoSync();
            usersSyncTimer = window.setInterval(() => {
                refreshUsersSync();
            }, 4000);
        }

        function stopUsersAutoSync() {
            if (usersSyncTimer) {
                window.clearInterval(usersSyncTimer);
                usersSyncTimer = null;
            }
        }

        function shouldRunUsersBackgroundSync() {
            if (currentDashboardTab !== 'users') {
                return false;
            }

            const gridView = document.getElementById('users-grid-view');
            if (!gridView || gridView.style.display === 'none') {
                return false;
            }

            return !window.currentUserDetail?.userId;
        }

        async function refreshUsersSync() {
            if (!shouldRunUsersBackgroundSync() || usersSyncInFlight) return;
            usersSyncInFlight = true;
            try {
                const users = await apiCall('GET', '/users');
                window.dashboardUsers = users;

                const filter = document.getElementById('user-filter');
                const currentValue = filter.value;
                filter.innerHTML = '<option value="">All Users</option>';

                users.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.user_id;
                    option.textContent = user.username;
                    filter.appendChild(option);
                });

                if (users.some(user => user.user_id === currentValue)) {
                    filter.value = currentValue;
                }

                displayUsers(users);
            } catch (error) {
                // Silent background sync; no alert spam.
            } finally {
                usersSyncInFlight = false;
            }
        }

        function createResourceDraft(data) {
            return {
                currency: Number.parseFloat(data?.currency || 0) || 0,
                inventory: (data?.inventory || []).map(item => ({
                    item_name: String(item.item_name || ''),
                    quantity: Number.parseInt(item.quantity || 0, 10) || 0
                })),
                dirty: false
            };
        }

        function sanitizeInventoryRows(rows) {
            return (rows || [])
                .map(item => ({
                    item_name: String(item.item_name || '').trim(),
                    quantity: Number.parseInt(item.quantity || 0, 10) || 0
                }))
                .filter(item => item.item_name && item.quantity > 0);
        }

        function buildInventoryItemSelectHtml(selectedItemName, onChangeName, index) {
            const normalizedSelected = String(selectedItemName || '').trim();
            const options = [...dashboardItemCatalog];
            if (normalizedSelected && !options.includes(normalizedSelected)) {
                options.unshift(normalizedSelected);
            }

            const optionMarkup = ['<option value="">Select Item</option>']
                .concat(options.map(itemName => {
                    const selected = itemName === normalizedSelected ? ' selected' : '';
                    return `<option value="${escHtml(itemName)}"${selected}>${escHtml(itemName)}</option>`;
                }))
                .join('');

            return `<select onchange="${onChangeName}(${index}, this.value)">${optionMarkup}</select>`;
        }

        function renderInventoryEditor(tbodyId, rows, onChangeName, onChangeQty, onRemoveClick, emptyMessage) {
            const tbody = document.getElementById(tbodyId);
            if (!rows.length) {
                tbody.innerHTML = `<tr><td colspan="3" class="inline-empty">${emptyMessage}</td></tr>`;
                return;
            }

            tbody.innerHTML = rows.map((item, index) => `
                <tr>
                    <td>${buildInventoryItemSelectHtml(item.item_name, onChangeName, index)}</td>
                    <td><input type="number" min="0" step="1" value="${Number.parseInt(item.quantity || 0, 10) || 0}" oninput="${onChangeQty}(${index}, this.value)"></td>
                    <td class="inventory-row-actions"><button class="btn-danger btn-tiny" onclick="${onRemoveClick}(${index})">Remove</button></td>
                </tr>
            `).join('');
        }

        function syncUserResourceEditor(data) {
            window.userResourceDraft = createResourceDraft(data);
            document.getElementById('detail-currency').textContent = window.userResourceDraft.currency.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
            document.getElementById('detail-currency-input').value = window.userResourceDraft.currency;
            renderInventoryEditor(
                'detail-inventory',
                window.userResourceDraft.inventory,
                'updateUserInventoryName',
                'updateUserInventoryQuantity',
                'removeUserInventoryRow',
                'No items'
            );
        }

        function syncCharacterResourceEditor(data) {
            window.characterResourceDraft = createResourceDraft(data);
            document.getElementById('character-currency').textContent = window.characterResourceDraft.currency.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
            document.getElementById('character-currency-input').value = window.characterResourceDraft.currency;
            renderInventoryEditor(
                'character-inventory',
                window.characterResourceDraft.inventory,
                'updateCharacterInventoryName',
                'updateCharacterInventoryQuantity',
                'removeCharacterInventoryRow',
                'No items for this character'
            );
        }

        function applyUserDetailData(userId, user, data, preserveFilter = true) {
            document.getElementById('detail-avatar').src = user.avatar_url || '';
            document.getElementById('detail-avatar').alt = user.username || '';
            document.getElementById('detail-username').textContent = user.username || '';
            document.getElementById('detail-role').textContent = 'Role: ' + (user.role || '');

            window.currentUserDetail = {
                userId,
                user,
                sheets: data.sheets || [],
                currency: data.currency || 0,
                inventory: data.inventory || []
            };

            if (!window.userResourceDraft || !window.userResourceDraft.dirty) {
                syncUserResourceEditor(data);
            }

            if (!preserveFilter) {
                document.getElementById('sheet-status-filter').value = '';
            }
            renderCharacterCards();
        }

        async function refreshCurrentUserDetail(silent = false) {
            if (!window.currentUserDetail || !window.currentUserDetail.userId) return;
            const userId = window.currentUserDetail.userId;
            const user = (window.dashboardUsers || []).find(u => u.user_id === userId) || window.currentUserDetail.user;
            if (!user) return;

            try {
                const data = await apiCall('GET', `/users/${userId}/detail`);
                applyUserDetailData(userId, user, data, true);

                if (window.currentCharacterDetail && window.currentCharacterDetail.sheet_id && !window.characterResourceDraft?.dirty) {
                    await refreshCurrentCharacterDetail(true);
                }
            } catch (err) {
                if (!silent) {
                    showAlert('users', 'Failed to load user detail: ' + err.message, 'error');
                }
            }
        }

        function getSheetById(sheetId) {
            const d = window.currentUserDetail;
            if (!d || !d.sheets) return null;
            return d.sheets.find(s => s.sheet_id === sheetId) || null;
        }

        function isSheetResolved(sheet) {
            return !!sheet && (sheet.status === 'Approved' || sheet.status === 'Denied');
        }

        function _attachUsersListClickDelegate() {
            if (_usersListenerAttached) return;
            _usersListenerAttached = true;
            document.getElementById('users-list').addEventListener('click', function (e) {
                const card = e.target.closest('.user-card');
                if (card && card.dataset.userId) openUserDetail(card.dataset.userId);
            });
        }

        async function loadUsersData() {
            try {
                const [users] = await Promise.all([
                    apiCall('GET', '/users'),
                    loadDashboardItemCatalog()
                ]);
                window.dashboardUsers = users;

                const filter = document.getElementById('user-filter');
                const currentValue = filter.value;
                filter.innerHTML = '<option value="">All Users</option>';

                users.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.user_id;
                    option.textContent = user.username;
                    filter.appendChild(option);
                });

                if (users.some(user => user.user_id === currentValue)) {
                    filter.value = currentValue;
                }

                _attachUsersListClickDelegate();
                displayUsers(users);
                if (pendingUsersNavigation) {
                    await handlePendingUsersNavigation();
                }
            } catch (error) {
                showAlert('users', 'Failed to load users: ' + error.message, 'error');
            }
        }

        function displayUsers(users) {
            const list = document.getElementById('users-list');
            const selectedUserId = document.getElementById('user-filter').value;
            const filteredUsers = selectedUserId
                ? users.filter(user => user.user_id === selectedUserId)
                : users;

            if (filteredUsers.length === 0) {
                list.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;"><div class="empty-state-icon">&#x1F465;</div><p>No users found</p></div>';
                return;
            }

            list.innerHTML = filteredUsers.map(user => `
                <div class="user-card" data-user-id="${user.user_id}">
                    <img class="user-avatar" src="${user.avatar_url}" alt="${escHtml(user.username)}">
                    <div class="user-meta">
                        <div class="user-name">${escHtml(user.username)}</div>
                        <div class="user-subtitle">Role: ${escHtml(user.role)}</div>
                        <div class="user-stats">
                            <div class="user-stat">
                                <span class="user-stat-label">Approved</span>
                                <span class="user-stat-value">${user.counts.approved}</span>
                            </div>
                            <div class="user-stat">
                                <span class="user-stat-label">Denied</span>
                                <span class="user-stat-value">${user.counts.denied}</span>
                            </div>
                            <div class="user-stat">
                                <span class="user-stat-label">Drafts</span>
                                <span class="user-stat-value">${user.counts.drafts}</span>
                            </div>
                            <div class="user-stat">
                                <span class="user-stat-label">On Discuss</span>
                                <span class="user-stat-value">${user.counts.discuss}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        // ===== USER DETAIL =====
        window.currentUserDetail = null;

        function escHtml(str) {
            return String(str || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function openUserDetail(userId, updateUrl = true) {
            const user = (window.dashboardUsers || []).find(u => u.user_id === userId);
            if (!user) return;

            document.getElementById('users-grid-view').style.display = 'none';
            document.getElementById('users-detail-view').style.display = 'block';
            document.getElementById('user-profile-content').style.display = 'block';
            document.getElementById('character-detail-panel').style.display = 'none';

            if (updateUrl) {
                history.pushState({ tab: 'users', userId }, '', `/users/${userId}`);
            }

            document.getElementById('detail-avatar').src = user.avatar_url || '';
            document.getElementById('detail-avatar').alt = user.username || '';
            document.getElementById('detail-username').textContent = user.username || '';
            document.getElementById('detail-role').textContent = 'Role: ' + (user.role || '');
            document.getElementById('detail-currency').textContent = '...';
            document.getElementById('detail-currency-input').value = '';
            document.getElementById('detail-inventory').innerHTML =
                '<tr><td colspan="3" class="inline-empty">Loading...</td></tr>';
            document.getElementById('character-cards-list').innerHTML =
                '<p style="color:#9ca3af;padding:12px;">Loading...</p>';
            document.getElementById('sheet-status-filter').value = '';
            document.getElementById('character-fields-list').innerHTML = '<tr><td colspan="2" class="inline-empty">Select a character to view fields</td></tr>';
            document.getElementById('character-inventory').innerHTML = '<tr><td colspan="3" class="inline-empty">Select a character to load resources</td></tr>';
            document.getElementById('character-currency').textContent = '—';
            document.getElementById('character-currency-input').value = '';

            window.currentUserDetail = { userId, user };
            window.userResourceDraft = null;
            window.currentCharacterDetail = null;
            window.characterResourceDraft = null;

            apiCall('GET', `/users/${userId}/detail`).then(data => {
                applyUserDetailData(userId, user, data, false);
            }).catch(err => {
                showAlert('users', 'Failed to load user detail: ' + err.message, 'error');
            });
        }

        function closeUserDetail(updateUrl = true) {
            if (updateUrl) {
                history.pushState({ tab: 'users' }, '', '/users');
            }
            document.getElementById('users-detail-view').style.display = 'none';
            document.getElementById('users-grid-view').style.display = 'block';
            window.currentUserDetail = null;
            window.userResourceDraft = null;
            window.currentCharacterDetail = null;
            window.characterResourceDraft = null;
        }

        function markUserResourcesDirty() {
            if (!window.userResourceDraft) {
                window.userResourceDraft = createResourceDraft(window.currentUserDetail || {});
            }
            const parsed = Number.parseFloat(document.getElementById('detail-currency-input').value);
            window.userResourceDraft.currency = Number.isFinite(parsed) ? parsed : 0;
            window.userResourceDraft.dirty = true;
            document.getElementById('detail-currency').textContent = window.userResourceDraft.currency.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }

        function addUserInventoryRow() {
            if (!window.userResourceDraft) {
                window.userResourceDraft = createResourceDraft(window.currentUserDetail || {});
            }
            window.userResourceDraft.inventory.push({ item_name: '', quantity: 1 });
            window.userResourceDraft.dirty = true;
            renderInventoryEditor('detail-inventory', window.userResourceDraft.inventory, 'updateUserInventoryName', 'updateUserInventoryQuantity', 'removeUserInventoryRow', 'No items');
        }

        function updateUserInventoryName(index, value) {
            if (!window.userResourceDraft) return;
            window.userResourceDraft.inventory[index].item_name = value;
            window.userResourceDraft.dirty = true;
        }

        function updateUserInventoryQuantity(index, value) {
            if (!window.userResourceDraft) return;
            window.userResourceDraft.inventory[index].quantity = Number.parseInt(value || 0, 10) || 0;
            window.userResourceDraft.dirty = true;
        }

        function removeUserInventoryRow(index) {
            if (!window.userResourceDraft) return;
            window.userResourceDraft.inventory.splice(index, 1);
            window.userResourceDraft.dirty = true;
            renderInventoryEditor('detail-inventory', window.userResourceDraft.inventory, 'updateUserInventoryName', 'updateUserInventoryQuantity', 'removeUserInventoryRow', 'No items');
        }

        function cancelUserResourceEdits() {
            if (!window.currentUserDetail) return;
            syncUserResourceEditor(window.currentUserDetail);
        }

        async function saveUserCurrency() {
            const d = window.currentUserDetail;
            if (!d || !window.userResourceDraft) return;
            try {
                const payload = {
                    currency: Number.parseFloat(document.getElementById('detail-currency-input').value || '0') || 0
                };
                const result = await apiCall('POST', `/users/${d.userId}/resources`, payload);
                window.currentUserDetail.currency = result.currency || 0;
                syncUserResourceEditor(window.currentUserDetail);
                showAlert('users', 'User currency updated.', 'success');
            } catch (err) {
                showAlert('users', 'Failed to save user currency: ' + err.message, 'error');
            }
        }

        async function saveUserInventory() {
            const d = window.currentUserDetail;
            if (!d || !window.userResourceDraft) return;
            try {
                const payload = {
                    inventory: sanitizeInventoryRows(window.userResourceDraft.inventory)
                };
                const result = await apiCall('POST', `/users/${d.userId}/resources`, payload);
                window.currentUserDetail.inventory = result.inventory || [];
                syncUserResourceEditor(window.currentUserDetail);
                document.getElementById('detail-currency-input').value = window.currentUserDetail.currency || 0;
                showAlert('users', 'User inventory updated.', 'success');
            } catch (err) {
                showAlert('users', 'Failed to save user inventory: ' + err.message, 'error');
            }
        }

        async function openCharacterDetail(sheetId, updateUrl = true) {
            const d = window.currentUserDetail;
            if (!d || !sheetId) return;
            document.getElementById('user-profile-content').style.display = 'none';
            document.getElementById('character-detail-panel').style.display = 'block';

            if (updateUrl) {
                history.pushState({ tab: 'users', userId: d.userId, sheetId }, '', `/users/${d.userId}/characters/${sheetId}`);
            }

            document.getElementById('character-detail-title').textContent = 'Loading character...';
            document.getElementById('character-detail-status').textContent = '';
            document.getElementById('character-fields-list').innerHTML = '<tr><td colspan="2" class="inline-empty">Loading fields...</td></tr>';
            document.getElementById('character-inventory').innerHTML = '<tr><td colspan="3" class="inline-empty">Loading resources...</td></tr>';
            document.getElementById('character-currency').textContent = '...';
            document.getElementById('character-currency-input').value = '';

            try {
                const detail = await apiCall('GET', `/users/${d.userId}/characters/${sheetId}`);
                window.currentCharacterDetail = detail;
                syncCharacterResourceEditor(detail);
                renderCharacterFields(detail.fields || []);
                document.getElementById('character-detail-title').textContent = detail.sheet_name || 'Character Detail';
                document.getElementById('character-detail-status').textContent = 'Status: ' + (detail.status || 'Unknown');
            } catch (err) {
                showAlert('users', 'Failed to load character detail: ' + err.message, 'error');
            }
        }

        async function refreshCurrentCharacterDetail(silent = false) {
            const d = window.currentUserDetail;
            const c = window.currentCharacterDetail;
            if (!d || !c || !c.sheet_id) return;
            try {
                const detail = await apiCall('GET', `/users/${d.userId}/characters/${c.sheet_id}`);
                window.currentCharacterDetail = detail;
                if (!window.characterResourceDraft || !window.characterResourceDraft.dirty) {
                    syncCharacterResourceEditor(detail);
                }
                renderCharacterFields(detail.fields || []);
                document.getElementById('character-detail-title').textContent = detail.sheet_name || 'Character Detail';
                document.getElementById('character-detail-status').textContent = 'Status: ' + (detail.status || 'Unknown');
            } catch (err) {
                if (!silent) {
                    showAlert('users', 'Failed to refresh character detail: ' + err.message, 'error');
                }
            }
        }

        function closeCharacterDetail(updateUrl = true) {
            document.getElementById('user-profile-content').style.display = 'block';
            document.getElementById('character-detail-panel').style.display = 'none';
            window.currentCharacterDetail = null;
            window.characterResourceDraft = null;
            if (updateUrl && window.currentUserDetail?.userId) {
                history.pushState({ tab: 'users', userId: window.currentUserDetail.userId }, '', `/users/${window.currentUserDetail.userId}`);
            }
        }

        function renderCharacterFields(fields) {
            const tbody = document.getElementById('character-fields-list');
            if (!fields.length) {
                tbody.innerHTML = '<tr><td colspan="2" class="inline-empty">No fields found for this character</td></tr>';
                return;
            }

            tbody.innerHTML = fields.map(field => `
                <tr>
                    <th>${escHtml(field.field_name)}</th>
                    <td>${escHtml(field.data || '—')}</td>
                </tr>
            `).join('');
        }

        function markCharacterResourcesDirty() {
            if (!window.characterResourceDraft) {
                window.characterResourceDraft = createResourceDraft(window.currentCharacterDetail || {});
            }
            const parsed = Number.parseFloat(document.getElementById('character-currency-input').value);
            window.characterResourceDraft.currency = Number.isFinite(parsed) ? parsed : 0;
            window.characterResourceDraft.dirty = true;
            document.getElementById('character-currency').textContent = window.characterResourceDraft.currency.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }

        function addCharacterInventoryRow() {
            if (!window.characterResourceDraft) {
                window.characterResourceDraft = createResourceDraft(window.currentCharacterDetail || {});
            }
            window.characterResourceDraft.inventory.push({ item_name: '', quantity: 1 });
            window.characterResourceDraft.dirty = true;
            renderInventoryEditor('character-inventory', window.characterResourceDraft.inventory, 'updateCharacterInventoryName', 'updateCharacterInventoryQuantity', 'removeCharacterInventoryRow', 'No items for this character');
        }

        function updateCharacterInventoryName(index, value) {
            if (!window.characterResourceDraft) return;
            window.characterResourceDraft.inventory[index].item_name = value;
            window.characterResourceDraft.dirty = true;
        }

        function updateCharacterInventoryQuantity(index, value) {
            if (!window.characterResourceDraft) return;
            window.characterResourceDraft.inventory[index].quantity = Number.parseInt(value || 0, 10) || 0;
            window.characterResourceDraft.dirty = true;
        }

        function removeCharacterInventoryRow(index) {
            if (!window.characterResourceDraft) return;
            window.characterResourceDraft.inventory.splice(index, 1);
            window.characterResourceDraft.dirty = true;
            renderInventoryEditor('character-inventory', window.characterResourceDraft.inventory, 'updateCharacterInventoryName', 'updateCharacterInventoryQuantity', 'removeCharacterInventoryRow', 'No items for this character');
        }

        function cancelCharacterResourceEdits() {
            if (!window.currentCharacterDetail) return;
            syncCharacterResourceEditor(window.currentCharacterDetail);
        }

        async function saveCharacterCurrency() {
            const d = window.currentUserDetail;
            const c = window.currentCharacterDetail;
            if (!d || !c || !window.characterResourceDraft) return;
            try {
                const payload = {
                    currency: Number.parseFloat(document.getElementById('character-currency-input').value || '0') || 0
                };
                const result = await apiCall('POST', `/users/${d.userId}/characters/${c.sheet_id}/resources`, payload);
                window.currentCharacterDetail = result;
                syncCharacterResourceEditor(result);
                renderCharacterFields(result.fields || []);
                showAlert('users', `Currency updated for ${result.sheet_name || 'character'}.`, 'success');
            } catch (err) {
                showAlert('users', 'Failed to save character currency: ' + err.message, 'error');
            }
        }

        async function saveCharacterInventory() {
            const d = window.currentUserDetail;
            const c = window.currentCharacterDetail;
            if (!d || !c || !window.characterResourceDraft) return;
            try {
                const payload = {
                    inventory: sanitizeInventoryRows(window.characterResourceDraft.inventory)
                };
                const result = await apiCall('POST', `/users/${d.userId}/characters/${c.sheet_id}/resources`, payload);
                window.currentCharacterDetail = result;
                syncCharacterResourceEditor(result);
                renderCharacterFields(result.fields || []);
                document.getElementById('character-currency-input').value = window.currentCharacterDetail.currency || 0;
                showAlert('users', `Inventory updated for ${result.sheet_name || 'character'}.`, 'success');
            } catch (err) {
                showAlert('users', 'Failed to save character inventory: ' + err.message, 'error');
            }
        }

        // ===== SHEET ACTION MODAL =====
        let _modalResolve = null;

        function openSheetModal(actionLabel, accentColor) {
            return new Promise(resolve => {
                _modalResolve = resolve;
                document.getElementById('modal-title').textContent = actionLabel + ' — Leave a comment?';
                document.getElementById('modal-comment').value = '';
                const btn = document.getElementById('modal-confirm-btn');
                btn.textContent = 'Confirm ' + actionLabel;
                btn.style.background = accentColor;
                btn.onclick = () => {
                    const comment = document.getElementById('modal-comment').value.trim();
                    closeSheetModal(true, comment);
                };
                const overlay = document.getElementById('sheet-action-modal');
                overlay.style.display = 'flex';
                document.getElementById('modal-comment').focus();
            });
        }

        function closeSheetModal(confirmed = false, comment = '') {
            document.getElementById('sheet-action-modal').style.display = 'none';
            if (_modalResolve) {
                _modalResolve({ confirmed, comment });
                _modalResolve = null;
            }
        }

        // Close modal on backdrop click
        document.addEventListener('click', function (e) {
            const overlay = document.getElementById('sheet-action-modal');
            if (e.target === overlay) closeSheetModal();
        });

        function renderCharacterCards() {
            const d = window.currentUserDetail;
            if (!d || !d.sheets) return;

            const filter = document.getElementById('sheet-status-filter').value;
            const sheets = filter ? d.sheets.filter(s => s.status === filter) : d.sheets;
            const list = document.getElementById('character-cards-list');

            if (!sheets.length) {
                list.innerHTML = '<p style="color:#9ca3af;text-align:center;padding:16px;">No characters found</p>';
                return;
            }

            const statusLabelMap = { Draft: 'Drafts', Discuss: 'On Discuss' };
            const badgeClassMap = {
                Approved:  'badge-approved',
                Denied:    'badge-denied',
                Draft:     'badge-draft',
                Discuss:   'badge-discuss',
                Submitted: 'badge-submitted',
            };

            list.innerHTML = sheets.map(s => {
                const iconUrl = s.has_icon
                    ? `/api/users/${d.userId}/sheets/${s.sheet_id}/icon`
                    : 'https://cdn.discordapp.com/embed/avatars/0.png';
                const badge = badgeClassMap[s.status] || 'badge-draft';
                const label = statusLabelMap[s.status] || s.status;
                const isResolved = s.status === 'Approved' || s.status === 'Denied';
                const actionButtons = isResolved
                    ? ''
                    : [
                        { cls: 'btn-approve', status: 'Approved', label: 'Approve', color: '#059669' },
                        { cls: 'btn-deny',    status: 'Denied',   label: 'Deny',    color: '#dc2626' },
                        { cls: 'btn-discuss', status: 'Discuss',  label: 'Discuss', color: '#3b82f6' },
                    ].map(b => {
                        const dis = s.status === b.status ? 'disabled' : '';
                        return `<button class="char-btn ${b.cls}" ${dis} onclick="promptSheetAction('${s.sheet_id}','${b.status}','${b.label}','${b.color}')">${b.label}</button>`;
                    }).join('');
                const viewButton = `<button class="char-btn btn-draft" onclick="openCharacterDetail('${s.sheet_id}')">View Character</button>`;

                return `
                    <div class="character-card" data-sheet-id="${s.sheet_id}">
                        <img class="char-icon" src="${iconUrl}" alt="${escHtml(s.sheet_name)}"
                             onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                        <div class="char-info">
                            <div class="char-name">${escHtml(s.sheet_name)}</div>
                            <span class="char-status-badge ${badge}">${label}</span>
                        </div>
                        <div class="char-actions">${viewButton}${actionButtons}</div>
                    </div>`;
            }).join('');
        }

        async function promptSheetAction(sheetId, newStatus, actionLabel, accentColor) {
            await refreshCurrentUserDetail(true);
            const freshSheet = getSheetById(sheetId);
            if (!freshSheet) {
                showAlert('users', 'This sheet could not be found. Refresh the page and try again.', 'error');
                return;
            }
            if (isSheetResolved(freshSheet)) {
                showAlert('users', `Action blocked. This sheet is already ${freshSheet.status}.`, 'error');
                return;
            }

            const { confirmed, comment } = await openSheetModal(actionLabel, accentColor);
            if (!confirmed) return;
            await changeSheetStatus(sheetId, newStatus, comment);
        }

        async function changeSheetStatus(sheetId, newStatus, comment) {
            const d = window.currentUserDetail;
            if (!d) return;
            try {
                await refreshCurrentUserDetail(true);
                const freshSheet = getSheetById(sheetId);
                if (!freshSheet) {
                    showAlert('users', 'This sheet could not be found. Refresh the page and try again.', 'error');
                    return;
                }
                if (isSheetResolved(freshSheet)) {
                    showAlert('users', `Action blocked. This sheet is already ${freshSheet.status}.`, 'error');
                    renderCharacterCards();
                    return;
                }

                const result = await apiCall('POST', `/users/${d.userId}/sheets/${sheetId}/status`, { status: newStatus, comment: comment || '' });
                const sheet = d.sheets.find(s => s.sheet_id === sheetId);
                if (sheet) sheet.status = newStatus;
                renderCharacterCards();
                const gridUser = (window.dashboardUsers || []).find(u => u.user_id === d.userId);
                if (gridUser) {
                    const counts = { approved: 0, denied: 0, drafts: 0, discuss: 0 };
                    d.sheets.forEach(s => {
                        if (s.status === 'Approved')      counts.approved++;
                        else if (s.status === 'Denied')   counts.denied++;
                        else if (s.status === 'Draft')    counts.drafts++;
                        else if (s.status === 'Discuss')  counts.discuss++;
                    });
                    gridUser.counts = counts;
                }

                if (result && result.notification_sent === false) {
                    showAlert('users', 'Status updated, but Discord embed was not sent: ' + (result.notification_error || 'Unknown notification error'), 'error');
                } else if (result && result.review_embed_closed === false) {
                    showAlert('users', 'Status updated, but review buttons could not be closed: ' + (result.review_embed_close_error || 'Unknown close error'), 'error');
                } else {
                    showAlert('users', `Status updated to ${newStatus}.`, 'success');
                }
            } catch (err) {
                showAlert('users', 'Failed to update status: ' + err.message, 'error');
                await refreshCurrentUserDetail(true);
                renderCharacterCards();
            }
        }

        async function handlePendingUsersNavigation() {
            if (!pendingUsersNavigation?.userId) return;

            const { userId, sheetId } = pendingUsersNavigation;
            const users = window.dashboardUsers || [];
            const matchingUser = users.find(user => user.user_id === userId);
            if (!matchingUser) return;

            pendingUsersNavigation = null;
            openUserDetail(userId, false);

            if (sheetId) {
                const waitForDetail = async () => {
                    for (let attempt = 0; attempt < 30; attempt++) {
                        if (window.currentUserDetail?.userId === userId && Array.isArray(window.currentUserDetail.sheets)) {
                            await openCharacterDetail(sheetId, false);
                            return;
                        }
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                };
                await waitForDetail();
            }
        }

        window.addEventListener('popstate', () => {
            const characterPath = window.location.pathname.match(/^\/users\/(\d{15,20})\/characters\/([A-Z0-9]{6})$/);
            if (characterPath) {
                pendingUsersNavigation = { userId: characterPath[1], sheetId: characterPath[2] };
                switchTab('users', null, false);
                return;
            }

            const userPath = window.location.pathname.match(/^\/users\/(\d{15,20})$/);
            if (userPath) {
                pendingUsersNavigation = { userId: userPath[1], sheetId: null };
                switchTab('users', null, false);
                return;
            }

            const pathToTab = Object.entries(TAB_PATHS)
                .find(([, path]) => path === window.location.pathname);
            pendingUsersNavigation = null;
            switchTab(pathToTab ? pathToTab[0] : 'overview', null, false);
        });

        // Load initial tab selected by Flask route
        switchTab('{{ active_tab|default("overview") }}', null, false);
    
