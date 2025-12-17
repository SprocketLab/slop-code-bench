// Simple web application
const express = require('express');

function logRequest(req) {
    console.log(`${req.method} ${req.url}`);
    return true;
}

function handleError(err) {
    console.error(err.message);
}

const app = express();

app.get('/', (req, res) => {
    logRequest(req);
    res.send('Hello World!');
});

app.listen(3000, () => {
    console.log('Server started on port 3000');
});
