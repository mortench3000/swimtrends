// CloudFront viewer-request function. Two jobs, in order:
//
// 1. Redirect any other host (i.e. www) to the apex with a 301, so there is one
//    canonical host. Every page already carries a rel=canonical pointing at the
//    apex, but a redirect is unambiguous and is what someone sharing a www link
//    expects.
//
// 2. Append /index.html to extensionless paths. The origin is an S3 REST
//    endpoint behind OAC, which — unlike an S3 *website* endpoint — has no
//    directory index document, and DefaultRootObject applies only to "/". So
//    /DM-L/12486 looks for the key "DM-L/12486", misses, and falls through to
//    the 403/404 -> /index.html error response, serving the generic SPA shell
//    instead of the prerendered page. That failure is silent, hence the tests in
//    tests/unit/test_web_stack.py.
//
// Paths that keep an extension are real objects (/robots.txt, /sitemap.xml,
// /assets/*, /data/*.json) and must pass through untouched.
//
// ES5 only: the CloudFront Functions runtime is not a full modern JS engine.
var APEX = 'swimtrends.dk';

// Decode-then-encode, so the result is encoded exactly once whether CloudFront
// handed the value over encoded or not. A malformed escape ("100%") makes
// decodeURIComponent throw; pass such a value through as-is.
function enc(s) {
  try {
    return encodeURIComponent(decodeURIComponent(s));
  } catch (e) {
    return s;
  }
}

// request.querystring is an object: { name: { value, multiValue?: [{ value }] } }.
// A repeated parameter arrives once, with all of its values in multiValue.
function queryString(qs) {
  var parts = [];
  for (var name in qs) {
    var values = qs[name].multiValue || [qs[name]];
    for (var i = 0; i < values.length; i++) {
      parts.push(enc(name) + '=' + enc(values[i].value));
    }
  }
  return parts.length ? '?' + parts.join('&') : '';
}

function handler(event) {
  var request = event.request;
  var host = request.headers.host && request.headers.host.value;

  // Keep the query: meet pages carry their filters in it (?discipline=&gender=),
  // and inbound utm_* tags should survive too.
  if (host && host !== APEX) {
    return {
      statusCode: 301,
      statusDescription: 'Moved Permanently',
      headers: {
        location: { value: 'https://' + APEX + request.uri + queryString(request.querystring || {}) },
      },
    };
  }

  var uri = request.uri;
  var last = uri.substring(uri.lastIndexOf('/') + 1);
  if (last === '') {
    request.uri = uri + 'index.html';
  } else if (last.indexOf('.') === -1) {
    request.uri = uri + '/index.html';
  }
  return request;
}
