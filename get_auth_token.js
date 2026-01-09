/**
 * Получение AUTH_TOKEN 
 * 
 * 1. Вставьте этот код в консоль (F12)
 * 2. Перейти на любую страницу 
 */

(function () {
    console.clear();
    console.log('═'.repeat(60));
    console.log('🔍 Ожидание токена...');
    console.log('═'.repeat(60));

    const origFetch = window.fetch;
    window.fetch = async function (input, init = {}) {
        // Ищем Authorization header
        if (init.headers) {
            let authToken = null;

            if (init.headers instanceof Headers) {
                authToken = init.headers.get('Authorization');
            } else if (typeof init.headers === 'object') {
                authToken = init.headers['Authorization'] || init.headers['authorization'];
            }

            if (authToken && authToken.startsWith('Bearer ')) {
                const token = authToken.replace('Bearer ', '');
                console.log('');
                console.log('═'.repeat(60));
                console.log(' AUTH_TOKEN НАЙДЕН:');
                console.log('═'.repeat(60));
                console.log(token);
                console.log('═'.repeat(60));

                // Копируем в буфер
                navigator.clipboard.writeText(token).then(() => {
                    console.log(' Токен скопирован в буфер!');
                }).catch(() => {
                    console.log('️  Скопируйте токен вручную');
                });
            }
        }

        return origFetch.apply(this, arguments);
    };

    // Также перехватываем XHR
    const origOpen = XMLHttpRequest.prototype.open;
    const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
        if (name.toLowerCase() === 'authorization' && value.startsWith('Bearer ')) {
            const token = value.replace('Bearer ', '');
            console.log('');
            console.log(' AUTH_TOKEN :', token.substring(0, 50) + '...');
            navigator.clipboard.writeText(token).catch(() => { });
        }
        return origSetHeader.apply(this, arguments);
    };

    console.log(' Interceptor активен.');
})();
