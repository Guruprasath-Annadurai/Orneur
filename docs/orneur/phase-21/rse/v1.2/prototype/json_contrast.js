// PROTOTYPE_ONLY
try { JSON.parse('{"n":NaN}'); console.log("js NaN: accepted"); } catch (e) { console.log("js NaN: rejected"); }
console.log("js duplicate key:", JSON.stringify(JSON.parse('{"a":1,"a":2}')));
console.log("js big exponent:", String(JSON.parse('{"b":1e999}').b));
