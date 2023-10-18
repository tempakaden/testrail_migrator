function prettifyJson() {
    console.log('Used prettify')
    var ugly = document.getElementById('id_custom_fields_matcher').value;
    var obj = JSON.parse(ugly);
    var pretty = JSON.stringify(obj, undefined, 4);
    document.getElementById('id_custom_fields_matcher').value = pretty;
}